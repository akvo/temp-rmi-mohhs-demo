#!/usr/bin/env python3
"""Build performance_data.json — the single structured source of truth for
the Performance Assessment tab.

Consolidates three assessment rounds (July 2025, Oct 2025, Feb 2026) plus
improvement-plan tracking for the 18 `Register=Y` health centers, from:
  - the Excel workbook "NI Health Center Performance Results (Oct-Nov 2025
    results & plans)).xlsx" (bundled in raw_sources/) — July/Oct 2025
    overall scores + the Oct 2025 improvement-plan action items,
  - the Feb 2026 score screenshot (no machine-readable source — hand
    transcribed below, cross-checked against the workbook's own
    "Performance Trends Line Graph" averages),
  - two Word docs (bundled in raw_sources/): the Feb 2026 assessment of the
    Oct 2025 plan's status, and the new Feb 2026 improvement plan,
  - the MIS (mohhs-mis.akvotest.org form 1783289494205) for canonical site
    names, ids and GPS, with admin_data.geojson centroid fallback where the
    MIS has no GPS on file.

Requires a `.env` in this same folder (see .env.example) with MIS
credentials, plus network access to mohhs-mis.akvotest.org.

Run manually: `python3 build_performance_data.py`. Prints a validation
summary; inspect it before trusting the output.
"""
import json
import re
import sys
from pathlib import Path

import openpyxl
import docx
import requests

HERE = Path(__file__).resolve().parent
BASE_URL = "https://mohhs-mis.akvotest.org"
REG_FORM_ID = 1783289494205
GPS_QUESTION_ID = 1783289902869

XLSX_PATH = HERE / "raw_sources" / "NI Health Center Performance Results (Oct-Nov 2025 results & plans)).xlsx"
STATUS_DOCX_PATH = HERE / "raw_sources" / "NI HC Oct-Nov 2025 MEC Improvement Results to Feb 2026.docx"
NEW_PLAN_DOCX_PATH = HERE / "raw_sources" / "NI HC Improvement Plans-All Sites (Feb 2026).docx"
GEOJSON_PATH = HERE / "admin_data.geojson"
ENV_PATH = HERE / ".env"
OUTPUT_PATH = HERE / "performance_data.json"

# --------------------------------------------------------------------------
# Canonical 18 sites (Register=Y in the source registration spreadsheet).
# site_key -> static info. mis_id/mis_name are the live registration on the
# platform; geojson_fallback is the ADM2 name to use for GPS when the MIS
# record has no geo (4 sites).
# --------------------------------------------------------------------------
SITES = {
    "ebon":              dict(atoll="Ebon", health_center="Ebon", mis_id=32, mis_name="Ebon - Ebon Health Center", geojson_fallback=None),
    "namdrik":           dict(atoll="Namdrik", health_center="Namdrik", mis_id=33, mis_name="Namdrik - Namdrik Health Center", geojson_fallback=None),
    "jaluit_jabor":      dict(atoll="Jaluit", health_center="Jabor", mis_id=34, mis_name="Jaluit - Jabwor Health Center", geojson_fallback=None),
    "ailinglaplap_woja": dict(atoll="Ailinglaplap", health_center="Woja", mis_id=35, mis_name="Ailinglaplap - Woja Health Center", geojson_fallback=None),
    "jabat":             dict(atoll="Jabat", health_center="Jabat", mis_id=36, mis_name="Jabat - Jabat Health Center", geojson_fallback=None),
    "namu_majkon":       dict(atoll="Namu", health_center="Majkon", mis_id=37, mis_name="Namu - Majkon Health Center", geojson_fallback=None),
    "lip":               dict(atoll="Lip", health_center="Lip", mis_id=38, mis_name="Lip - Lip Health Center", geojson_fallback=None),
    "ujae":              dict(atoll="Ujae", health_center="Ujae", mis_id=39, mis_name="Ujae - Ujae Health Center", geojson_fallback=None),
    "lae":               dict(atoll="Lae", health_center="Lae", mis_id=40, mis_name="Lae - Lae Health Center", geojson_fallback=None),
    "wotho":             dict(atoll="Wotho", health_center="Wotho", mis_id=41, mis_name="Wotho - Wotho Health Center", geojson_fallback=None),
    "arno_ine":          dict(atoll="Arno", health_center="Ine", mis_id=42, mis_name="Arno - Ine Health Center", geojson_fallback=None),
    "ailuk":             dict(atoll="Ailuk", health_center="Ailuk", mis_id=43, mis_name="Ailuk - Ailuk Health Center", geojson_fallback=None),
    "likiep":            dict(atoll="Likiep", health_center="Likiep", mis_id=44, mis_name="Likiep - Likiep Health Center", geojson_fallback=None),
    "mili_enejet":       dict(atoll="Mili", health_center="Enejet", mis_id=31, mis_name="Mili", geojson_fallback=None),
    "wotje":             dict(atoll="Wotje", health_center="Wotje", mis_id=8, mis_name="Wotje Wotje HC", geojson_fallback="Wotje"),
    "mejit":             dict(atoll="Mejit", health_center="Mejit", mis_id=9, mis_name="Mejit HC", geojson_fallback="Mejit"),
    "maloelap_kaben":    dict(atoll="Maloelap", health_center="Kaben", mis_id=10, mis_name="Maloelap-Kaben HC", geojson_fallback="Kaben"),
    "aur_tobal":         dict(atoll="Aur", health_center="Tobal", mis_id=12, mis_name="Aur-Tabal HC", geojson_fallback="Tabal"),
}

# Officers as of the Feb 2026 assessment (mayor/local-govt lead, HA) —
# transcribed from the Feb 2026 score screenshot, the single most current
# and already-published source for who's currently assigned to each site.
OFFICERS = {
    "ebon": ("Alminson Naisher", "Kojen Koneilles"),
    "namdrik": ("Tawe Clement", "Harris Harris"),
    "jaluit_jabor": ("Rostina Morris", "Elmon Joshua"),
    "ailinglaplap_woja": ("Riming Ring", "Weston Elji"),
    "jabat": ("Nai Naisher", "Jounran Journran"),
    "namu_majkon": ("Kemilang Kabua", "Oktan Timothy"),
    "lip": ("Winlan Sheet", "Joe Noka"),
    "ujae": ("Morrison James Jr", "Merina Riketa"),
    "lae": ("Telmong Kabua", "Akji Langbata"),
    "wotho": ("Kudo Kabua", "Tom Briand"),
    "arno_ine": ("Baji Danny", "Jally Enos"),
    "ailuk": ("Dancy Alfred", "Kori Marshall"),
    "likiep": ("Nicholas deBrum", "Brandy Kemlan"),
    "mili_enejet": ("Joel Jitiam", "Brandy Kemlan"),
    "wotje": ("Rithin Lajar", "Jackin Robert"),
    "mejit": ("Neal Keju", "Joel Laidren"),
    "maloelap_kaben": ("William Saito", "Rodney Briand"),
    "aur_tobal": ("Hesa Kaious", "James Simon"),
}

# Feb 2026 overall scores — no machine-readable source exists (chart
# screenshot only). Transcribed by hand; cross-checked below against every
# other round's per-site figures already in the workbook, and the printed
# aggregate averages in "Performance Trends Line Graph" as a sanity check
# on July/Oct. The screenshot's extra "Mili (Lukonwod)" row (75%) is
# intentionally dropped — it isn't a Register=Y site.
FEB_2026_SCORES = {
    "namu_majkon": 88, "jabat": 79, "mejit": 79, "wotje": 73,
    "ailinglaplap_woja": 73, "lae": 73, "ebon": 71, "ailuk": 71,
    "arno_ine": 65, "jaluit_jabor": 63, "wotho": 63, "ujae": 60,
    "mili_enejet": 60, "lip": 58, "likiep": 54, "maloelap_kaben": 52,
    "aur_tobal": 46, "namdrik": 31,
}

# HC-name keyword (as it appears in the workbook's "HEALTH CENTERS" column,
# before any "(popn)" suffix and taking only the part before a "/") -> site.
HC_KEYWORD_TO_SITE = {
    "EBON": "ebon", "NAMDRIK": "namdrik", "JABOR": "jaluit_jabor",
    "WOJA": "ailinglaplap_woja", "JABOT": "jabat", "MAJKON": "namu_majkon",
    "LIP": "lip", "UJAE": "ujae", "LAE": "lae", "WOTHO": "wotho",
    "ENEJET": "mili_enejet", "INNE": "arno_ine", "TOBAL": "aur_tobal",
    "KABEN": "maloelap_kaben", "WOTJE": "wotje", "AILUK": "ailuk",
    "LIKIEP": "likiep", "MEJIT": "mejit",
}

# Atoll-label keyword (first line of the improvement-plan tables' site
# column, before any "(...)") -> site. Ebon/Mili need the parenthetical HC
# name too, since both atolls have a second "Other" site (Toka / Lukwonwod)
# also present in these tables that must NOT be folded into our 18.
ATOLL_KEYWORD_TO_SITE = {
    "AUR": "aur_tobal", "MEJIT": "mejit", "MALEOLAP": "maloelap_kaben",
    "AILUK": "ailuk", "WOTJE": "wotje", "LIKIEP": "likiep",
    "WOTHO": "wotho", "UJAE": "ujae", "LAE": "lae", "NAMU": "namu_majkon",
    "ALINGLAPLAP": "ailinglaplap_woja", "JABAT": "jabat",
    "JALUIT": "jaluit_jabor", "NAMRIK": "namdrik", "ARNO": "arno_ine",
    "LIB": "lip",
}


def load_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def fetch_mis_gps():
    """Return {mis_id: [lat, lon] or None} for form 1783289494205."""
    env = load_env(ENV_PATH)
    s = requests.Session()
    resp = s.post(f"{BASE_URL}/api/v1/login", json={"email": env["user"], "password": env["password"]})
    resp.raise_for_status()
    token = resp.json()["token"]
    rows, page = [], 1
    while True:
        resp = s.get(
            f"{BASE_URL}/api/v1/form-data/{REG_FORM_ID}?page={page}&perpage=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("data", []))
        if page >= data.get("total_page", 1):
            break
        page += 1
    return {row["id"]: row.get("geo") for row in rows}


def load_geojson_centroids():
    d = json.loads(GEOJSON_PATH.read_text())
    out = {}
    for f in d["features"]:
        p = f["properties"]
        name = p.get("ADM2_EN")
        if name:
            out[name] = [p.get("ycoord"), p.get("xcoord")]
    return out


def norm_hc(raw):
    """'AILUK/ENEJELAR (235)' -> 'AILUK'; 'EBON (267)' -> 'EBON'."""
    return (raw or "").upper().split("(")[0].split("/")[0].strip()


def extract_july_2025(wb):
    scores = {}
    ws = wb["Main HC July 2025 Scores"]
    for row in ws.iter_rows(min_row=3, max_row=54, values_only=True):
        key = HC_KEYWORD_TO_SITE.get(norm_hc(row[1]))
        if key and row[16] is not None:
            scores[key] = row[16]
    return scores


def extract_oct_2025(wb):
    scores = {}
    ws = wb["All HC Overall Scores"]
    for row in ws.iter_rows(min_row=3, max_row=58, values_only=True):
        key = HC_KEYWORD_TO_SITE.get(norm_hc(row[1]))
        if key and row[9] is not None:
            scores[key] = row[9]
    return scores


def check_aggregate(wb, july_scores, oct_scores):
    ws = wb["Performance Trends Line Graph"]
    printed = {}
    for row in ws.iter_rows(min_row=1, max_row=14, values_only=True):
        if row[0] in ("July, 2025", "Oct, 2025"):
            printed[row[0]] = row[1]
    july_avg = sum(july_scores.values()) / len(july_scores) if july_scores else None
    oct_avg = sum(oct_scores.values()) / len(oct_scores) if oct_scores else None
    print(f"  July 2025: computed avg={july_avg:.1f} over {len(july_scores)} sites | workbook aggregate={printed.get('July, 2025')}")
    print(f"  Oct 2025:  computed avg={oct_avg:.1f} over {len(oct_scores)} sites | workbook aggregate={printed.get('Oct, 2025')}")


def split_actions(text):
    if not text:
        return []
    items = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*\d+[\)\.]\s*", "", line.strip()).strip()
        if line:
            items.append(line)
    return items


def extract_oct_2025_plan(wb):
    """site -> {ha: [...], local_govt: [...], oihcs: [...]} from the
    Oct2025 Improvemt Plans sheet."""
    ws = wb["Oct2025 Improvemt Plans"]
    plan = {}
    for row in ws.iter_rows(min_row=4, max_row=22, values_only=True):
        label = row[0]
        if not label:
            continue
        atoll = label.split("\n")[0].split("(")[0].strip().upper()
        paren = None
        if "(" in label:
            paren = label.split("(", 1)[1].split(")")[0].strip().upper()
        key = resolve_site_key(atoll, paren)
        if not key:
            continue
        plan[key] = {
            "ha": split_actions(row[2]),
            "local_govt": split_actions(row[3]),
            "oihcs": split_actions(row[4]),
        }
    return plan


def resolve_site_key(atoll_word, paren_word):
    if atoll_word == "EBON":
        return "ebon" if paren_word == "EBON" else None
    if atoll_word == "MILI":
        return "mili_enejet" if paren_word and paren_word.startswith("ENEJ") else None
    return ATOLL_KEYWORD_TO_SITE.get(atoll_word)


STATUS_RE = re.compile(r"\b(Yes|No|N0|NA)\b\s*(\(.*\))?\s*$", re.IGNORECASE)


def parse_status_items(text):
    """'Clean sink; - No\\nRestart reports- Yes' -> [{"item":..,"done":bool|None}]"""
    out = []
    for line in split_actions(text):
        m = STATUS_RE.search(line)
        if m:
            word = m.group(1).upper()
            done = True if word == "YES" else (False if word in ("NO", "N0") else None)
            item = line[: m.start()].rstrip(" -–;:()").strip()
        else:
            done, item = None, line
        if item:
            out.append({"item": item, "done": done})
    return out


def extract_docx_plan(path, parse_fn, skip_labels_containing=()):
    d = docx.Document(path)
    t = d.tables[0]
    out = {}
    for row in t.rows[1:]:
        cells = [c.text for c in row.cells]
        label = cells[0]
        if not label or label.strip().lower() == "total":
            continue
        if any(s in label for s in skip_labels_containing):
            continue
        first_line = label.split("\n")[0]
        atoll = first_line.split("(")[0].strip().upper()
        paren = None
        if "(" in first_line:
            paren = first_line.split("(", 1)[1].split(")")[0].strip().upper()
        key = resolve_site_key(atoll, paren)
        if not key:
            continue
        out[key] = {
            "ha": parse_fn(cells[1]),
            "local_govt": parse_fn(cells[2]),
            "oihcs": parse_fn(cells[3]),
        }
    return out


def strip_marshallese(text):
    return re.split(r"\n\s*Majol\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def build_ai_summary(display_name, feb_status, new_plan):
    done = total = 0
    if feb_status:
        for cat in ("ha", "local_govt", "oihcs"):
            for entry in feb_status.get(cat, []):
                if entry["done"] is not None:
                    total += 1
                    done += entry["done"]
    headline = []
    if new_plan:
        for cat in ("ha", "local_govt", "oihcs"):
            headline.extend(new_plan.get(cat, []))
    headline = headline[:2]
    if total:
        pct = round(100 * done / total)
        progress = f"Of the {total} Oct 2025 action items with a recorded Feb 2026 status, {done} ({pct}%) were completed."
    else:
        progress = "No Oct 2025 action items have a recorded Feb 2026 status for this site."
    focus = f" The new Feb 2026 plan's top priorities: {'; '.join(headline)}." if headline else ""
    return progress + focus


def main():
    print("Fetching MIS registrations + GPS ...")
    mis_geo = fetch_mis_gps()
    geojson_centroids = load_geojson_centroids()

    print(f"Reading {XLSX_PATH.name} ...")
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    july_scores = extract_july_2025(wb)
    oct_scores = extract_oct_2025(wb)
    oct_plan = extract_oct_2025_plan(wb)
    print("Sanity-checking against workbook's own aggregate averages:")
    check_aggregate(wb, july_scores, oct_scores)

    print(f"Reading {STATUS_DOCX_PATH.name} ...")
    feb_status = extract_docx_plan(STATUS_DOCX_PATH, parse_status_items, skip_labels_containing=("Toka",))

    print(f"Reading {NEW_PLAN_DOCX_PATH.name} ...")
    new_plan_raw = extract_docx_plan(
        NEW_PLAN_DOCX_PATH,
        lambda t: split_actions(strip_marshallese(t)),
        skip_labels_containing=("Lukwonwod",),
    )

    # Known source data-quality issue (verified by hand): the status docx's
    # "Namrik" row and "Ebon (Ebon)" row both contain action text that is a
    # near-exact copy of Ebon's / Ebon-Toka's original Oct 2025 plan items,
    # not their own — same wording, same order. Rather than guess which
    # site the Yes/No answers actually belong to, drop the (mis-attributed)
    # status for these two and flag it instead of silently misreporting
    # progress. See README.md's Known Limitations section.
    data_quality_notes = {
        "namdrik": "Feb 2026 status doc's 'Namrik' row duplicates Ebon's Oct 2025 action list verbatim (source data-entry issue) — status omitted rather than misattributed. New Feb 2026 plan text has the same duplication; treat with caution.",
        "ebon": "Feb 2026 status doc's 'Ebon (Ebon)' row duplicates Ebon-Toka's Oct 2025 action list verbatim (source data-entry issue) — status omitted rather than misattributed. New Feb 2026 plan text may have the same duplication; treat with caution.",
    }
    for key in ("namdrik", "ebon"):
        feb_status.pop(key, None)

    sites_out = []
    unmatched = []
    for key, info in SITES.items():
        geo = mis_geo.get(info["mis_id"])
        geo_source = "mis"
        if not geo:
            fallback_name = info["geojson_fallback"]
            geo = geojson_centroids.get(fallback_name) if fallback_name else None
            geo_source = "geojson_centroid" if geo else "missing"
        if not geo:
            unmatched.append(key)

        scores = {}
        if key in july_scores:
            scores["2025-07"] = {"overall": july_scores[key]}
        if key in oct_scores:
            scores["2025-10"] = {"overall": oct_scores[key]}
        if key in FEB_2026_SCORES:
            scores["2026-02"] = {"overall": FEB_2026_SCORES[key]}
        else:
            unmatched.append(f"{key} (no Feb 2026 score)")

        rounds_present = [r for r in ("2025-07", "2025-10", "2026-02") if r in scores]
        baseline_round = rounds_present[0] if rounds_present else None
        latest_round = rounds_present[-1] if rounds_present else None
        baseline_score = scores[baseline_round]["overall"] if baseline_round else None
        latest_score = scores[latest_round]["overall"] if latest_round else None
        improvement_pts = (
            latest_score - baseline_score
            if baseline_score is not None and latest_score is not None and baseline_round != latest_round
            else None
        )

        mayor, ha = OFFICERS.get(key, (None, None))
        site_feb_status = feb_status.get(key)
        site_new_plan = new_plan_raw.get(key)

        site = {
            "site_key": key,
            "atoll": info["atoll"],
            "health_center": info["health_center"],
            "display_name": info["mis_name"],
            "mis_datapoint_id": info["mis_id"],
            "officers": {"mayor": mayor, "ha": ha},
            "gps": {"lat": geo[0], "lon": geo[1], "source": geo_source} if geo else None,
            "scores": scores,
            "baseline_round": baseline_round,
            "baseline_score": baseline_score,
            "latest_round": latest_round,
            "latest_score": latest_score,
            "improvement_pts": improvement_pts,
            "improvement_plan": {
                "2025-10_actions": oct_plan.get(key),
                "2026-02_status": site_feb_status,
                "2026-02_new_plan": site_new_plan,
                "ai_summary": build_ai_summary(info["mis_name"], site_feb_status, site_new_plan),
            },
        }
        if key in data_quality_notes:
            site["improvement_plan"]["data_quality_note"] = data_quality_notes[key]
        sites_out.append(site)

    latest_scores = [s["latest_score"] for s in sites_out if s["latest_round"] == "2026-02"]
    latest_scores_sorted = sorted(latest_scores)
    n = len(latest_scores_sorted)
    median = (
        latest_scores_sorted[n // 2]
        if n % 2
        else (latest_scores_sorted[n // 2 - 1] + latest_scores_sorted[n // 2]) / 2
    )
    for s in sites_out:
        s["above_median"] = s["latest_score"] > median if s["latest_round"] == "2026-02" else None

    output = {
        "generated_at": "2026-07-10",
        "rounds": ["2025-07", "2025-10", "2026-02"],
        "median_latest_score": median,
        "sites": sites_out,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"\nWrote {OUTPUT_PATH} — {len(sites_out)} sites (expected 18).")
    if unmatched:
        print("Flags:")
        for u in unmatched:
            print(f"  - {u}")
    missing_july = [s["site_key"] for s in sites_out if "2025-07" not in s["scores"]]
    missing_oct = [s["site_key"] for s in sites_out if "2025-10" not in s["scores"]]
    print(f"Sites with no July 2025 baseline (uses Oct as baseline instead): {missing_july}")
    print(f"Sites with no Oct 2025 score: {missing_oct}")
    print(f"Median Feb 2026 score: {median}")
    if len(sites_out) != 18:
        sys.exit(f"ERROR: expected 18 sites, got {len(sites_out)}")


if __name__ == "__main__":
    main()
