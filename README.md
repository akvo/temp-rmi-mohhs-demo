# MOHHS RMI Health Center Dashboards

A single Streamlit app, two tabs, no sidebar:

- **Performance Assessment** — score trends (July 2025 / Oct 2025 / Feb
  2026) and improvement-plan tracking for the 18 `Register=Y` health
  centers on the platform.
- **JMP WASH Facility Assessment** — JMP-2018 WASH service-level ladders
  (Basic / Limited / No service) for the 19 submitted facility
  assessments.

Both tabs read from a pre-built JSON file each. The app itself makes no API
calls and does no data processing — all of that happens in the two
`build_*.py` ETL scripts, run separately (and only when you need to refresh
the data). See **[VISUALS.md](VISUALS.md)** for exactly what each chart
shows, where its data comes from, and what processing was applied to it.

## Package contents

```
app.py                      entry point — page config, tabs, nothing else
performance_tab.py          Performance Assessment tab (render_performance_tab)
jmp_wash_tab.py              JMP WASH tab (render_jmp_wash_tab)
chart_helpers.py            shared theming + the Folium map builder both tabs use

build_performance_data.py   ETL → performance_data.json (needs raw_sources/ + .env)
build_jmp_data.py           ETL → jmp_data.json (needs only .env, pulls live from the MIS)

performance_data.json       pre-built data the Performance tab reads
jmp_data.json                pre-built data the JMP tab reads
admin_data.geojson          RMI administrative-boundary reference (GPS fallback source)
raw_sources/                 the 3 source documents build_performance_data.py parses
JMP_SCORING.md               JMP-2018 domain scoring formulas + a documented limitation

requirements.txt
.env.example                 copy to .env and fill in real MIS credentials
```

## Setup

Requires Python 3.11+.

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env with real MIS credentials
```

## Running the dashboard

```bash
streamlit run app.py
```

The app reads `performance_data.json` and `jmp_data.json` as committed —
you do **not** need to run the ETL scripts just to view the dashboard.

## Regenerating the data

Only needed when the underlying MIS submissions or source documents change.

```bash
python3 build_jmp_data.py            # needs only .env + network access
python3 build_performance_data.py    # also needs raw_sources/ + admin_data.geojson
```

Both scripts print a validation summary — read it before trusting the
output. `build_performance_data.py` in particular cross-checks its July/Oct
2025 extraction against the source workbook's own printed averages and
will flag anything that doesn't reconcile.

**The Feb 2026 Performance scores have no machine-readable source** — the
only record was a chart screenshot, hand-transcribed into
`build_performance_data.py`'s `FEB_2026_SCORES` dict. If a new round
happens, that dict (and the two Word-doc-derived improvement-plan sections)
needs a new manual source and a new hand-transcription — there's no API or
file to point the script at instead.

## Data sources — API reference

Base URL: `https://mohhs-mis.akvotest.org`. Both ETL scripts authenticate
the same way and call a subset of these endpoints:

| Endpoint | Method | Used by | Purpose |
|---|---|---|---|
| `/api/v1/login` | POST | both | Get a bearer token from `.env` credentials |
| `/api/v1/form-data/<form_id>?page=&perpage=` | GET | both | Paginated list of a form's datapoints — registration form `1783289494205` (names/GPS) and JMP form `1783393878133` |
| `/api/v1/data-details/<id>` | GET | JMP only | Full answers + uuid for one JMP submission (the list endpoint doesn't include full answers) |
| `/api/v1/administration/<id>` | GET | JMP only | Resolve a JMP record's administration id to its atoll/island name |

`build_performance_data.py` additionally reads 3 local files (bundled in
`raw_sources/`): the July/Oct 2025 scores + Oct-2025 improvement-plan
workbook, and two Word docs (Feb-2026 status-of-Oct-plan, new Feb-2026
plan) — plus `admin_data.geojson` as a GPS fallback for 4 registrations
that have no coordinates on the platform itself. Full detail on which
sheet/column/table each field comes from is in the script's own comments
and in `VISUALS.md`.

## Known limitations (carried over from the source data, not bugs)

- **Feb 2026 Performance scores**: hand-transcribed from a chart
  screenshot — no machine-readable source exists.
- **Mili (Lukonwod)**: the Feb 2026 screenshot lists a 19th site not in the
  canonical `Register=Y` list; intentionally excluded from
  `performance_data.json`.
- **Ebon / Namdrik Oct-2025 status**: the Feb-2026 status Word doc's rows
  for these two sites duplicate other sites' action-item text verbatim (a
  source data-entry issue, confirmed by exact-text comparison). Rather than
  guess the correct attribution, their `2026-02_status` is left empty and
  the mismatch is recorded in `data_quality_note` on those two site records
  (not currently surfaced in the UI — intentionally, per a "PoC, not
  production" decision — but present in the JSON for anyone auditing it).
- **JMP Basic Sanitation**: excludes the menstrual-hygiene criterion, since
  this form's questions don't collect it. See `JMP_SCORING.md`.
