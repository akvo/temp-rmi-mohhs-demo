"""Performance Assessment: live-round fetch + merge on top of the curated
static baseline (performance_data.json).

The static file's rounds (2025-07, 2025-10, 2026-02) are hand-curated from
an Excel workbook + Word docs + a hand-transcribed screenshot -- verified,
cross-checked, with documented data-quality overrides for 2 sites. This
module NEVER touches those rounds. It only ever adds rounds strictly newer
than the static file's latest round -- every such round is shown as soon as
any site has reported for it, however partial (a round rolls out over days/
weeks as HAs visit each island, so "wait for full coverage" would mean it
never shows up until the last straggler reports). Each live round's
site-coverage count is still tracked (live_round_meta) so the UI can flag
a round as partial rather than implying every site has been assessed.
"""
from collections import defaultdict
from datetime import datetime

import performance_calc

REG_FORM_ID = 1783289494205
PERF_FORM_ID = 1783387964086

Q_MONITORING_ROUND = 1783388344461
# final_score is raw points out of 48; overall_score_in_out_of_48 is the same
# thing as a 0-100 percentage (round(100 * final_score / 48)). The dashboard's
# scores -- including every curated static round -- are percentages, so the
# percentage field is what a round's "overall" must come from; the raw points
# are kept alongside it only to caption the per-group breakdown ("37 of 48").
Q_FINAL_SCORE = 1783388344557
Q_OVERALL_PCT = 1783388344558

# The nine scored question groups behind final_score. `qid` is the group's own
# `autofield` score question (the per-group "... Score" field), which the MIS
# stores as a plain answer on every submission -- the "Final Scores" group's
# `*_display` autofields are display_only and come back as None, so they are
# NOT usable here.
#
# max_points is not exposed by the API (the form definition carries no
# per-option scores), so it is derived from the group's own scoring questions:
# one point per `yes` on an option question, one point per selected value on a
# multiple_option question excluding the non-scoring `none` / `other` choices
# (`which_month` is a follow-up detail, not scored). That rule reproduces every
# group score AND final_score exactly for all 16 July 2026 submissions, and the
# maxima below sum to 48 -- the denominator the form's own
# "Overall Score in % (out of 48)" autofield uses.
SCORE_GROUPS = [
    dict(key="community_accountability", qid=1783388344469, max_points=4,
         label="Community Accountability", short="Community accountability"),
    dict(key="community_health", qid=1783388344475, max_points=2,
         label="Community Engagement, Feedback & Accountability — Community health", short="Community health"),
    dict(key="community_engagement", qid=1783388344481, max_points=2,
         label="Community Engagement, Feedback & Accountability — Community engagement", short="Community engagement"),
    dict(key="staffing_credentials", qid=1783388344484, max_points=1,
         label="Staffing — Credentials", short="Staffing credentials"),
    dict(key="facility_structure", qid=1783388344508, max_points=11,
         label="Facility & Supplies — Structure", short="Facility: structure"),
    dict(key="facility_cleanliness", qid=1783388344524, max_points=7,
         label="Facility & Supplies — Cleanliness & Infection control", short="Facility: cleanliness"),
    dict(key="facility_meds_storage", qid=1783388344530, max_points=2,
         label="Facility & Supplies — Meds storage", short="Facility: meds storage"),
    dict(key="services_reporting", qid=1783388344536, max_points=9,
         label="Services, Outreach, Prevention & Clinical Care — Reporting", short="Services: reporting"),
    dict(key="services_delivery", qid=1783388344546, max_points=10,
         label="Services, Outreach, Prevention & Clinical Care — Service delivery", short="Services: delivery"),
]

TOTAL_MAX_POINTS = sum(g["max_points"] for g in SCORE_GROUPS)
assert TOTAL_MAX_POINTS == 48, TOTAL_MAX_POINTS

ROUND_OPTION_TO_KEY = {
    "july_2025": "2025-07",
    "october_2025": "2025-10",
    "february_2026": "2026-02",
    "july_2026": "2026-07",
    "october_2026": "2026-10",
}

# data-details' `created` field, e.g. "13-07-2026 19:11:54"
CREATED_FORMAT = "%d-%m-%Y %H:%M:%S"


def _parse_points(raw):
    """One autofield score -> int, or None if absent/unparseable. The API
    returns these as a str for some submissions and an int for others."""
    if raw is None:
        return None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def resolve_site_uuids(reg_rows, sites_static):
    """{site_key: registration_uuid} for the 18 canonical sites.

    reg_rows: the paginated listing from form 1783289494205 (id + uuid per
    row) -- no extra API calls needed beyond what's already fetched for GPS.
    sites_static: performance_data.json's "sites" list, each already
    carrying its registration FormData id as mis_datapoint_id.
    """
    uuid_by_id = {row["id"]: row["uuid"] for row in reg_rows}
    return {
        s["site_key"]: uuid_by_id[s["mis_datapoint_id"]]
        for s in sites_static
        if s["mis_datapoint_id"] in uuid_by_id
    }


def fetch_live_rounds(client, sites_static, static_rounds, reg_rows=None):
    """Returns (live_rounds, live_meta).

    live_rounds: {round_key: {site_key: {"overall": pct, "points": raw,
      "groups": {group_key: points}}}} -- every round strictly after
      static_rounds[-1] (plain string comparison is valid: fixed "YYYY-MM"
      width) that has at least one reporting site. A round with partial
      coverage is included, not held back -- see module docstring. "overall"
      is a 0-100 percentage, on the same scale as the static rounds;
      "points" is the same score as raw points out of TOTAL_MAX_POINTS, and
      "groups" breaks those points down per question group (see
      SCORE_GROUPS) -- a group whose autofield is missing or unparseable is
      simply absent from it.
    live_meta: {round_key: {"n_sites", "total_sites"}} -- site-coverage
      count per live round, for a "partial" UI caption.
    """
    if reg_rows is None:
        reg_rows = client.list_form_data(REG_FORM_ID)
    uuid_to_site_key = {v: k for k, v in resolve_site_uuids(reg_rows, sites_static).items()}
    last_static = static_rounds[-1]

    by_round = defaultdict(dict)  # round_key -> {site_key: (record_dict, created_dt)}
    perf_rows = client.list_form_data(PERF_FORM_ID)
    print(f"[performance_live] Fetching {len(perf_rows)} submission detail(s) concurrently ...", flush=True)
    details = client.data_details_many([row["id"] for row in perf_rows])
    for row, detail in zip(perf_rows, details):
        site_key = uuid_to_site_key.get(detail["uuid"])
        if site_key is None:
            continue  # not one of the 18 canonical registrations (e.g. test entries)

        answers = {a["question"]: a["value"] for a in detail["answers"]}
        round_raw = answers.get(Q_MONITORING_ROUND)
        round_opt = round_raw[0] if isinstance(round_raw, list) and round_raw else round_raw
        round_key = ROUND_OPTION_TO_KEY.get(round_opt)
        if round_key is None or round_key <= last_static:
            continue  # unknown option, or at/before the permanent static baseline -- never touched

        points = _parse_points(answers.get(Q_FINAL_SCORE))
        if points is None:
            if answers.get(Q_FINAL_SCORE) is not None:
                print(f"[performance_live] Skipping record id={row['id']}: unparseable final_score "
                      f"{answers[Q_FINAL_SCORE]!r}", flush=True)
            continue
        # Prefer the form's own percentage autofield so the dashboard shows
        # exactly the number the MIS shows; recompute it from the raw points
        # only if that field is missing/unparseable on this submission.
        pct = _parse_points(answers.get(Q_OVERALL_PCT))
        if pct is None:
            pct = int(round(100 * points / TOTAL_MAX_POINTS))
        record = {
            "overall": pct,
            "points": points,
            "groups": {
                g["key"]: g_points
                for g in SCORE_GROUPS
                if (g_points := _parse_points(answers.get(g["qid"]))) is not None
            },
        }

        created = datetime.strptime(detail["created"], CREATED_FORMAT)
        existing = by_round[round_key].get(site_key)
        if existing is None or created > existing[1]:  # de-dupe: latest submission (by created time) wins
            by_round[round_key][site_key] = (record, created)

    live_rounds = {
        round_key: {k: v[0] for k, v in site_scores.items()}
        for round_key, site_scores in by_round.items()
    }
    live_meta = {
        round_key: {"n_sites": len(site_scores), "total_sites": len(sites_static)}
        for round_key, site_scores in by_round.items()
    }
    return live_rounds, live_meta


def merge_live_rounds(static_data, live_rounds, live_meta):
    """Pure function -- does not mutate static_data. Adds every live round
    on top of the static baseline, recomputes baseline/latest/improvement/
    median/above_median via performance_calc, and stamps round_source /
    live_round_meta for the UI to distinguish live rounds (and flag partial
    coverage) from static ones.
    """
    rounds = list(static_data["rounds"]) + sorted(live_rounds)
    sites = []
    for s in static_data["sites"]:
        scores = dict(s["scores"])
        for round_key, site_scores in live_rounds.items():
            if s["site_key"] in site_scores:
                scores[round_key] = dict(site_scores[s["site_key"]])
        sites.append({**s, "scores": scores, **performance_calc.round_summary(scores, rounds)})

    median, above_flags = performance_calc.median_and_flags(sites, rounds[-1])
    for s in sites:
        s["above_median"] = above_flags[s["site_key"]]

    return {
        **static_data,
        "rounds": rounds,
        "sites": sites,
        "median_latest_score": median,
        "round_source": {r: ("live" if r in live_rounds else "static") for r in rounds},
        "live_round_meta": live_meta,
    }
