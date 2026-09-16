"""JMP WASH Facility Assessment: fetch + JMP-2018 domain scoring.

Shared by build_jmp_data.py (offline snapshot regeneration) and
jmp_wash_tab.py (live-at-runtime fetch) so there is exactly one
implementation of the scoring formulas -- see JMP_SCORING.md for the
per-domain rationale, including the documented Basic-Sanitation limitation
(menstrual hygiene isn't asked about by this form).
"""
from collections import Counter

JMP_FORM_ID = 1783393878133
REG_FORM_ID = 1783289494205

# Registrations with no GPS on the platform (pre-existing sites registered
# before this project's scripts) -- same admin_data.geojson ADM2-centroid
# fallback used when these were registered / when the earlier import ran.
GPS_FALLBACK = {
    "Maloelap-Kaben HC": (8.893026856500057, 170.8401931977796),
    "Mejit HC": (10.284074900500059, 170.87060244675698),
    "Wotje Wotje HC": (9.452038402000056, 170.24023593667266),
}

# question variableName -> question id (form 1783393878133, as published)
QID = {
    "G-W1": 1783393879415, "G-W2": 1783393880056, "G-W3": 1783393880697,
    "G-S1": 1783393881979, "G-S2": 1783393882620, "G-S3": 1783393883261,
    "G-S4": 1783393883902, "G-S5": 1783393884543,
    "G-H1": 1783393885825, "G-H2": 1783393886466,
    "G-C1": 1783393887748, "G-C2": 1783393888389, "G-C3": 1783393889030,
    "G-E1": 1783393890312, "G-E2": 1783393890953, "G-E3": 1783393891594,
}

WATER_IMPROVED = {"piped_water", "borehole_tubewell", "rainwater", "bottled_water", "tanker_truck"}
SANITATION_IMPROVED = {"flush_toilet", "pour_flush_toilet", "pit_latrine_with_slab", "composting_toilet"}

DOMAINS = [
    ("water", "Water", "Service level for drinking water"),
    ("sanitation", "Sanitation", "Service level for sanitation"),
    ("hygiene", "Hygiene", "Service level for hand hygiene"),
    ("waste", "Health-care waste management", "Service level for health-care waste management"),
    ("cleaning", "Environmental cleaning", "Service level for environmental cleaning"),
]


def water_level(answers):
    v = answers.get("G-W1")
    if v not in WATER_IMPROVED:
        return "No service"
    if answers.get("G-W2") == "yes" and answers.get("G-W3") == "yes":
        return "Basic service"
    return "Limited service"


def sanitation_level(answers):
    v = answers.get("G-S1")
    if v not in SANITATION_IMPROVED:
        return "No service"
    if all(answers.get(q) == "yes" for q in ("G-S2", "G-S3", "G-S4", "G-S5")):
        return "Basic service"
    return "Limited service"


def hygiene_level(answers):
    h1, h2 = answers.get("G-H1") == "yes", answers.get("G-H2") == "yes"
    if h1 and h2:
        return "Basic service"
    if h1 or h2:
        return "Limited service"
    return "No service"


def waste_level(answers):
    c1, c2, c3 = answers.get("G-C1"), answers.get("G-C2"), answers.get("G-C3")
    if c1 == "yes_sharps_infectious_and_non_infectious" and c2 == "yes" and c3 == "yes":
        return "Basic service"
    if c1 == "no" and c2 == "no" and c3 == "no":
        return "No service"
    return "Limited service"


def cleaning_level(answers):
    e1, e2 = answers.get("G-E1"), answers.get("G-E2")
    if e1 == "yes" and e2 == "yes_all":
        return "Basic service"
    if e1 == "no" and e2 == "none":
        return "No service"
    return "Limited service"


LEVEL_FN = {"water": water_level, "sanitation": sanitation_level, "hygiene": hygiene_level,
            "waste": waste_level, "cleaning": cleaning_level}


def fetch_jmp_records(client):
    """Paginated list + per-id data-details, form 1783393878133."""
    listing = client.list_form_data(JMP_FORM_ID)
    records = []
    for i, row in enumerate(listing, start=1):
        print(f"[jmp_fetch] Fetching detail {i}/{len(listing)} (id={row['id']}) ...", flush=True)
        records.append(client.data_details(row["id"]))
    return records


def build_jmp_dataset(client):
    """Returns {"domains", "levels", "sites"} -- the exact shape jmp_data.json
    already has, so callers (the offline script, the live tab) don't need to
    know or care whether the data just came off the wire."""
    jmp_records = fetch_jmp_records(client)

    admin_ids = sorted({r["administration"] for r in jmp_records})
    print(f"[jmp_fetch] Resolving {len(admin_ids)} administration id(s) ...", flush=True)
    admin_info = {}
    for aid in admin_ids:
        r = client.administration(aid)
        parts = r["full_name"].split("|")
        admin_info[aid] = {"island": r["name"], "atoll": parts[1] if len(parts) > 1 else r["full_name"]}

    sites_out = []
    for rec in jmp_records:
        answers = {}
        for a in rec["answers"]:
            var = next((k for k, qid in QID.items() if qid == a["question"]), None)
            if var:
                answers[var] = a["value"][0] if isinstance(a["value"], list) else a["value"]

        geo = rec.get("geo") or GPS_FALLBACK.get(rec["name"])
        if geo is None:
            raise ValueError(f"No GPS (live or fallback) for {rec['name']!r} -- add it to GPS_FALLBACK.")

        levels = {key: LEVEL_FN[key](answers) for key, _, _ in DOMAINS}
        meets_all = all(v == "Basic service" for v in levels.values())

        sites_out.append({
            "name": rec["name"],
            "uuid": rec["uuid"],
            "atoll": admin_info[rec["administration"]]["atoll"],
            "island": admin_info[rec["administration"]]["island"],
            "gps": {"lat": geo[0], "lon": geo[1]},
            "levels": levels,
            "answers": answers,
            "meets_jmp_basic_wash": meets_all,
        })

    sites_out.sort(key=lambda s: s["name"])

    return {
        "domains": [{"key": k, "label": lbl, "question": q} for k, lbl, q in DOMAINS],
        "levels": ["Basic service", "Limited service", "No service"],
        "sites": sites_out,
    }


def validation_summary(sites_out):
    """CLI-only: per-domain level counts + meets-basic-WASH count, printed by
    build_jmp_data.py after writing the file."""
    lines = []
    for key, label, _ in DOMAINS:
        counts = Counter(s["levels"][key] for s in sites_out)
        lines.append(f"  {label}: {dict(counts)}")
    meets = sum(1 for s in sites_out if s["meets_jmp_basic_wash"])
    lines.append(f"  Meets full JMP basic WASH (all 5 domains): {meets}/{len(sites_out)}")
    return "\n".join(lines)
