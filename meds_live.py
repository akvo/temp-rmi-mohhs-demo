"""NI HC - Essential Meds and Supplies Checklist (form 1783385736711):
live fetch + shaping for the Essential Meds tab.

Unlike the Performance Assessment, this checklist has no curated static
baseline -- there is no Excel/Word history for it, so everything the tab
shows comes from the MIS. This module is the *fetch* side: build_live_data.py
calls it and writes meds_data.json, which meds_tab.py then reads. The app
itself makes no API calls at runtime.

The checklist has two independently scored sections, each a list of
multiple-option "tick what you have in stock" categories:

  - Essential Supplies (7 categories, 52 items)
  - Essential Meds    (22 categories, 60 items)

Both the category structure and the per-category maxima are read from the
published form definition at build time rather than hardcoded: at 29 categories
and 112 individual items, a hardcoded copy would be a maintenance liability
and would silently drift the first time an item is added to the checklist.
"""
from collections import defaultdict
from datetime import datetime

MEDS_FORM_ID = 1783385736711
REG_FORM_ID = 1783289494205

Q_MONITORING_ROUND = 1783479425408
# The assessment date. Its numeric id happens to equal the Essential Supplies
# *question-group* id — different id namespaces, not a mix-up.
Q_DATE = 1783385736713

# `none` and `other` are bookkeeping choices, not stocked items: they are
# excluded from both the score and the maximum. Counting one selected option
# per remaining item reproduces every `*_score` autofield on every submission
# that has one, and the resulting maxima (52 / 60) reproduce every
# `*_percentage` autofield as round(100 * score / max) -- verified across all
# 9 scored submissions on the form.
NON_ITEM_OPTIONS = {"none", "other"}

# question-group id -> the section it scores, with that group's own score /
# percentage autofield questions.
SECTION_SPECS = [
    dict(key="supplies", group_id=1783385736713, label="Essential Supplies",
         short="Supplies", score_qid=1783479425414, pct_qid=1783479425415),
    dict(key="meds", group_id=1783385736714, label="Essential Meds",
         short="Meds", score_qid=1783479425438, pct_qid=1783479425439),
]

ROUND_OPTION_TO_KEY = {
    "july_2025": "2025-07",
    "october_2025": "2025-10",
    "february_2026": "2026-02",
    "july_2026": "2026-07",
    "october_2026": "2026-10",
}

CREATED_FORMAT = "%d-%m-%Y %H:%M:%S"

# Round keys are "YYYY-MM" and a round opens in the month it is named for, so
# the round a dated submission belongs to is the latest round whose key is <=
# that submission's own "YYYY-MM". Rounds run long (the July 2026 checklists
# were filled in from July into August, as HAs reach each island), which is
# why this compares against the round *start* rather than matching the month.
#
# Used ONLY as a fallback for a submission that left Monitoring Round blank --
# a stated round is always honoured as-is, never second-guessed. Cross-checked
# against every submission that does state a round: it reproduces all 8 real
# ones. The only disagreement is the "Test Akvo - Deden" test entry, which
# states July 2025 but is dated July 2026 -- itself internally inconsistent,
# and excluded anyway for not being a registered health center.
ROUND_KEYS_ASCENDING = sorted(set(ROUND_OPTION_TO_KEY.values()))


def _log(msg):
    print(f"[meds_live] {msg}", flush=True)


def build_schema(form_json):
    """Derive the checklist's structure from the published form definition.

    Returns {"sections": [{key, label, short, score_qid, pct_qid, max_points,
    categories: [{key, qid, label, max_points, items: [{value, label}]}]}]} --
    JSON-safe (question ids as ints are fine as *values*; they are never used
    as dict keys) so it can go straight into the disk cache.
    """
    groups = {g["id"]: g for g in form_json["question_group"]}
    sections = []
    for spec in SECTION_SPECS:
        categories = []
        for q in groups[spec["group_id"]]["question"]:
            if q["type"] != "multiple_option":
                continue
            items = [
                {"value": o["value"], "label": o["label"]}
                for o in q["option"]
                if o["value"] not in NON_ITEM_OPTIONS
            ]
            categories.append(dict(
                key=q["name"], qid=q["id"], label=q.get("label") or q["name"],
                max_points=len(items), items=items,
            ))
        sections.append(dict(
            **{k: v for k, v in spec.items() if k != "group_id"},
            max_points=sum(c["max_points"] for c in categories),
            categories=categories,
        ))
    return {"sections": sections}


def _submission_month(answers, created_raw):
    """The submission's own "YYYY-MM" -- the date answered on the form, or
    the record's created timestamp if that question was left blank."""
    raw = answers.get(Q_DATE)
    if isinstance(raw, str) and len(raw) >= 7:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%Y-%m")
        except ValueError:
            pass
    return datetime.strptime(created_raw, CREATED_FORMAT).strftime("%Y-%m")


def infer_round(answers, created_raw):
    """Fallback round for a submission with no Monitoring Round selected --
    see ROUND_KEYS_ASCENDING. None if it predates every known round."""
    month = _submission_month(answers, created_raw)
    prior = [r for r in ROUND_KEYS_ASCENDING if r <= month]
    return prior[-1] if prior else None


def _parse_int(raw):
    """One autofield value -> int, or None if absent/unparseable (the API
    returns these as a str for some submissions, an int for others)."""
    if raw is None:
        return None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def _score_record(schema, answers):
    """One submission's answers -> {section_key: {score, max, pct, categories}}.

    Per category, `have` is the list of stocked item values actually ticked
    (anything the form no longer offers is dropped, so `have` is always a
    subset of the schema's items and "missing" is a clean set difference).

    The section score comes from the form's own autofield when present, and
    is otherwise recomputed by counting ticked items -- a handful of early
    submissions predate those autofields being added to the form.
    """
    sections = {}
    for section in schema["sections"]:
        categories = {}
        for cat in section["categories"]:
            valid = {i["value"] for i in cat["items"]}
            ticked = [v for v in (answers.get(cat["qid"]) or []) if v in valid]
            categories[cat["key"]] = {"have": ticked}
        counted = sum(len(c["have"]) for c in categories.values())

        score = _parse_int(answers.get(section["score_qid"]))
        if score is None:
            score = counted
            derived = True
        else:
            derived = False
        pct = _parse_int(answers.get(section["pct_qid"]))
        if pct is None:
            pct = int(round(100 * score / section["max_points"])) if section["max_points"] else 0

        sections[section["key"]] = {
            "score": score, "max": section["max_points"], "pct": pct,
            "score_derived": derived, "categories": categories,
        }
    return sections


def fetch_meds_rounds(client, sites_static, reg_rows=None):
    """Returns {"schema": ..., "rounds": {round_key: {site_key: record}},
    "meta": {...}} -- JSON-safe throughout, so it serialises straight to
    meds_data.json.

    record: {"sections": {...}, "created": "DD-MM-YYYY HH:MM:SS"}.

    Submissions are dropped when they aren't one of the canonical registered
    sites. A submission that left Monitoring Round blank is filed under the
    round its own date falls in (see infer_round) and flagged with
    "round_inferred" rather than discarded -- a complete checklist shouldn't
    be lost to one unset dropdown. Per site and round the latest submission
    still wins, so an inferred one only ever surfaces when nothing newer with
    a stated round exists. Counts land in "meta" so the tab can say all of
    this out loud instead of silently showing fewer health centers.
    """
    import performance_live  # shared uuid<->site_key join, one implementation

    schema = build_schema(client.form_schema(MEDS_FORM_ID))
    if reg_rows is None:
        reg_rows = client.list_form_data(REG_FORM_ID)
    uuid_to_site_key = {v: k for k, v in performance_live.resolve_site_uuids(reg_rows, sites_static).items()}

    rows = client.list_form_data(MEDS_FORM_ID)
    _log(f"Fetching {len(rows)} submission detail(s) concurrently ...")
    details = client.data_details_many([row["id"] for row in rows])

    by_round = defaultdict(dict)  # round_key -> {site_key: (record, created_dt)}
    skipped_unknown_site = skipped_no_round = 0
    for detail in details:
        site_key = uuid_to_site_key.get(detail["uuid"])
        if site_key is None:
            skipped_unknown_site += 1
            continue

        answers = {a["question"]: a["value"] for a in detail["answers"]}
        round_raw = answers.get(Q_MONITORING_ROUND)
        round_opt = round_raw[0] if isinstance(round_raw, list) and round_raw else round_raw
        round_key = ROUND_OPTION_TO_KEY.get(round_opt)
        inferred = round_key is None
        if inferred:
            round_key = infer_round(answers, detail["created"])
            if round_key is None:
                skipped_no_round += 1
                continue

        created = datetime.strptime(detail["created"], CREATED_FORMAT)
        existing = by_round[round_key].get(site_key)
        if existing is None or created > existing[1]:  # de-dupe: latest submission wins
            record = {
                "sections": _score_record(schema, answers),
                "created": detail["created"],
                "round_inferred": inferred,
                "date": _submission_month(answers, detail["created"]),
            }
            by_round[round_key][site_key] = (record, created)

    rounds = {rk: {sk: v[0] for sk, v in sites.items()} for rk, sites in by_round.items()}
    meta = {
        "rounds": {
            rk: {
                "n_sites": len(sites),
                "total_sites": len(sites_static),
                "inferred_sites": sorted(sk for sk, rec in sites.items() if rec["round_inferred"]),
            }
            for rk, sites in rounds.items()
        },
        "skipped_unknown_site": skipped_unknown_site,
        "skipped_no_round": skipped_no_round,
        "n_submissions": len(details),
    }
    n_inferred = sum(len(r["inferred_sites"]) for r in meta["rounds"].values())
    _log(f"{len(rounds)} round(s); skipped {skipped_unknown_site} non-registered and "
         f"{skipped_no_round} undateable submission(s); {n_inferred} site(s) filed by inferred round.")
    return {"schema": schema, "rounds": rounds, "meta": meta}
