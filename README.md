# MOHHS RMI Health Center Dashboards

A single Streamlit app, three tabs, no sidebar:

- **Performance Assessment** — score trends (July 2025 / Oct 2025 / Feb
  2026, plus any newer live-verified round) and improvement-plan tracking
  for the 18 `Register=Y` health centers on the platform. Newer rounds are
  layered on top of a fixed curated baseline — see **"Where the data comes
  from"** below.
- **Essential Meds & Supplies** — stock availability against the 112-item
  "NI HC - Essential Meds and Supplies Checklist" (form `1783385736711`):
  two independently scored sections (Essential Supplies, 52 items;
  Essential Meds, 60 items), a per-category breakdown per health center,
  the specific items each one is out of, and the items missing at the most
  health centers. Sourced entirely from the MIS — this checklist has no
  curated static baseline.
- **JMP WASH Facility Assessment** — JMP-2018 WASH service-level ladders
  (Basic / Limited / No service) for the submitted facility assessments.
  This was a one-time assessment (not an ongoing round like Performance),
  so it reads the committed `jmp_data.json` snapshot directly — no live API
  call at runtime. Re-run `build_jmp_data.py` and commit the result if the
  assessment is ever redone or corrected.

See **[VISUALS.md](VISUALS.md)** for exactly what each chart shows and what
processing was applied to it.

## Package contents

```
app.py                      entry point — page config, tabs, nothing else
performance_tab.py          Performance Assessment tab (render_performance_tab)
meds_tab.py                  Essential Meds & Supplies tab (render_meds_tab)
jmp_wash_tab.py              JMP WASH tab (render_jmp_wash_tab)
chart_helpers.py            shared theming + the Folium map builder all three tabs use
                            (the four files above are the whole runtime — none of them touch the network)

mis_client.py               shared MIS API client — credentials, login, pagination (build scripts only)
performance_live.py          perf-round fetch, site-matching, dedup-by-latest-submission, merge-with-baseline
meds_live.py                 Essential Meds fetch + scoring — derives the checklist structure from the published form
jmp_fetch.py                 JMP fetch + JMP-2018 domain scoring
performance_calc.py          round-summary/median math (shared by the Performance tab and its ETL script)

build_live_data.py          ETL → performance_live_data.json + meds_data.json — re-run routinely as assessments come in
build_performance_data.py   ETL → performance_data.json — the curated static baseline (needs raw_sources/ + credentials)
build_jmp_data.py           ETL → jmp_data.json — regenerate only if the JMP assessment is redone/corrected

performance_data.json       curated historical baseline the Performance tab always starts from
performance_live_data.json   MIS snapshot: rounds newer than that baseline
meds_data.json               MIS snapshot: the Essential Meds & Supplies tab's only data source
jmp_data.json                the JMP tab's only data source — a one-time assessment
admin_data.geojson          RMI administrative-boundary reference (GPS fallback source)
raw_sources/                 the 3 source documents build_performance_data.py parses
JMP_SCORING.md               JMP-2018 domain scoring formulas + a documented limitation

requirements.txt
.env.example                  copy to .env — credentials for the build scripts only, not the app
```

## Setup

Requires Python 3.11+.

```bash
pip install -r requirements.txt
```

**To run the dashboard, that is all you need** — the committed JSON
snapshots are the app's only data source, so no credentials are required,
locally or on the deployed instance.

Credentials are only needed to *rebuild* those snapshots:

```bash
cp .env.example .env   # then edit .env with real MIS credentials
```

`.streamlit/secrets.toml` works too (see `.streamlit/secrets.toml.example`).
Since only the build scripts read credentials, a deployment never needs
them configured at all.

## Running the dashboard

```bash
streamlit run app.py
```

All three tabs read committed JSON — no network calls, no credentials, and
the whole app renders in about a second. See "Where the data comes from"
below for how to refresh the data.

## Where the data comes from

**The app makes no API calls at runtime.** Every tab reads a JSON file
committed to this repo. That means the deployed instance needs no MIS
credentials, loads in about a second, and keeps serving when
mohhs-mis.akvotest.org is down — which it is often enough (502s) that
fetching at request time was a real availability risk.

| File | Built by | Feeds |
|---|---|---|
| `performance_data.json` | `build_performance_data.py` | curated baseline rounds (Jul 2025, Oct 2025, Feb 2026) |
| `performance_live_data.json` | `build_live_data.py` | every round newer than that baseline |
| `meds_data.json` | `build_live_data.py` | the whole Essential Meds & Supplies tab |
| `jmp_data.json` | `build_jmp_data.py` | the whole JMP WASH tab |

The tradeoff is that the data is as-of the last build. Both snapshot files
carry a `fetched_at` stamp (not surfaced in the UI — check the file, or the
build script's summary, if you need to know how old the data is). To
refresh:

```bash
python3 build_live_data.py   # ~90s against the test instance
git add performance_live_data.json meds_data.json && git commit
```

Read the script's summary before committing — it reports per-round site
coverage and names anything it skipped or inferred.

### What build_live_data.py does

- **Performance Assessment**: the three baseline rounds in
  `performance_data.json` are hand-curated from an Excel workbook, two Word
  docs, and a transcribed chart screenshot — cross-checked and documented —
  and are **never** overwritten or reconciled against MIS data. The script
  only ever captures rounds strictly *newer* than that baseline, and a round
  is included as soon as one site has reported (a round rolls out over
  days/weeks as HAs reach each island, so waiting for full coverage would
  mean never showing it). If more than one submission exists for the same
  site and round, the latest `created` wins. A round's score comes from the
  form's own `overall_score_in_out_of_48` percentage autofield, *not* the
  raw `final_score` points, so it sits on the same 0–100 scale as the
  curated rounds; the raw points are kept alongside to caption the
  per-question-group breakdown ("37 of 48").
- **Essential Meds & Supplies**: the whole dataset, including the checklist
  structure (29 categories, 112 items) read from the *published form
  definition* rather than hardcoded. Submissions from a datapoint that isn't
  one of the canonical registrations are excluded and counted. A submission
  that left **Monitoring Round blank** is not discarded — it is filed under
  the round its own form date falls in (the latest round whose "YYYY-MM" key
  is <= the submission's month; rounds run long, so this compares against
  the round start rather than matching the month) and flagged. A stated
  round is always honoured as-is, never second-guessed. This inference
  reproduces the stated round on all 8 real submissions that have one; the
  sole disagreement is the "Test Akvo - Deden" test entry, which claims July
  2025 but is dated July 2026 and is excluded anyway as unregistered.
  Because the latest submission per site+round still wins, an inferred round
  only surfaces when nothing newer with a stated round exists.
- Site-matching for both joins a submission's `uuid` to its parent
  registration record's `uuid` on form `1783289494205`. One registration
  listing is fetched and shared between the two.
- Everything the script skips or infers is reported **by name** in its own
  summary output — read it before committing. In the UI, a health center
  whose round was inferred says so in its detail panel.

Console progress logging (`print(...)`) is emitted at each network call so a
slow build doesn't look stuck.

## Regenerating the static data

`build_live_data.py` is the one to re-run routinely, whenever new
assessments have come in — see "Where the data comes from" above.

`build_performance_data.py` is still the **only** way to produce the curated
historical baseline — run it by hand whenever a round is fully reconciled
and the team wants to "graduate" it into the permanent record (the same way
the Feb 2026 round was added). It needs the source Excel/Word files in
`raw_sources/`. `build_jmp_data.py` regenerates `jmp_data.json` — only
needed if the JMP assessment is ever redone or a data-entry error gets
corrected. Commit the regenerated files afterward.

```bash
python3 build_jmp_data.py            # needs only credentials + network access
python3 build_performance_data.py    # also needs raw_sources/ + admin_data.geojson
```

Both scripts print a validation summary — read it before trusting the
output. `build_performance_data.py` in particular cross-checks its July/Oct
2025 extraction against the source workbook's own printed averages and
will flag anything that doesn't reconcile.

**The Feb 2026 Performance scores have no machine-readable source** — the
only record was a chart screenshot, hand-transcribed into
`build_performance_data.py`'s `FEB_2026_SCORES` dict. Any *earlier* round
without a live form to pull from needs the same manual-transcription
treatment; only rounds submitted through the live Performance Assessment
form (`1783387964086`) get picked up automatically by `build_live_data.py`.

## Data sources — API reference

Base URL: `https://mohhs-mis.akvotest.org`. **Only the build scripts call
these endpoints** — the dashboard itself never does. All of them go through
`mis_client.py`.

| Endpoint | Method | Used by | Purpose |
|---|---|---|---|
| `/api/v1/login` | POST | all | Get a bearer token from credentials (`.env` or `st.secrets`) |
| `/api/v1/form-data/<form_id>?page=&perpage=` | GET | all | Paginated list of a form's datapoints — registration `1783289494205` (names/GPS/uuid), JMP `1783393878133`, Performance Assessment `1783387964086`, Essential Meds checklist `1783385736711` |
| `/api/v1/data-details/<id>` | GET | all | Full answers + uuid for one submission (the list endpoint doesn't include full answers) |
| `/api/v1/form/<form_id>` | GET | `build_live_data.py` | Published form definition — used to derive the Essential Meds checklist structure, labels and maxima instead of hardcoding them |
| `/api/v1/administration/<id>` | GET | JMP only | Resolve a JMP record's administration id to its atoll/island name |

Two endpoints worth knowing about if you need to find another form:
`/api/v1/forms` lists **only parent forms** — the child forms
(Performance Assessment, JMP, Essential Meds) do not appear there.
`/api/v1/forms/published` lists all of them, and the instance publishes its
full OpenAPI schema at `/api/schema/`.

`build_performance_data.py` additionally reads 3 local files (bundled in
`raw_sources/`): the July/Oct 2025 scores + Oct-2025 improvement-plan
workbook, and two Word docs (Feb-2026 status-of-Oct-plan, new Feb-2026
plan) — plus `admin_data.geojson` as a GPS fallback for 4 registrations
that have no coordinates on the platform itself. Full detail on which
sheet/column/table each field comes from is in the script's own comments
and in `VISUALS.md`.

## Known limitations (carried over from the source data, not bugs)

- **A malformed live JMP submission would break a re-run of `build_jmp_data.py`**:
  the JMP form currently has at least one test/junk submission (name
  "Untitled", no GPS on file and no `GPS_FALLBACK` entry) that makes
  `jmp_fetch.build_jmp_dataset()` raise rather than skip it. Doesn't affect
  the deployed JMP tab (it just reads the already-committed `jmp_data.json`,
  built before this record appeared) — only matters if/when someone reruns
  `build_jmp_data.py` to regenerate the snapshot; that record needs cleaning
  up or a `GPS_FALLBACK` entry first.
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
