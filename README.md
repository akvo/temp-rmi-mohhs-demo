# MOHHS RMI Health Center Dashboards

A single Streamlit app, three tabs, no sidebar:

- **Performance Assessment** — score trends (July 2025 / Oct 2025 / Feb
  2026, plus any newer live-verified round) and improvement-plan tracking
  for the 18 `Register=Y` health centers on the platform, with a per-question-group
  score breakdown. Newer rounds are layered on top of a fixed curated
  baseline — see **"Where the data comes from"** below.
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
chart_helpers.py            shared theming all three tabs use
map_helpers.py              the map component's Python side + the quantile colour scale
map_component/index.html     the map itself — MapLibre GL, in-map controls and legend
                            (the files above are the whole runtime — none of them touch the network)

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

## Maps

All three maps are **MapLibre GL JS**, as a small Streamlit component
(`map_component/index.html` + `map_helpers.py`). No mapping Python package is
involved; MapLibre loads from a CDN and the component talks to Streamlit over
the documented postMessage protocol, so there is no build step.

**Controls and legend live inside the map**, as real corner-anchored MapLibre
controls: the measure picker and basemap picker top-left, the legend
bottom-right. Switching measure or basemap is handled entirely in the browser
— no Streamlit rerun, so it is instant. Only a marker *click* comes back to
Python, because that drives the detail panel outside the map.

- **"Colour markers by" picks the measure**: the overall score or any one of
  the nine question groups on the Performance tab; a section or any one of the
  29 checklist categories on Essential Meds; the five JMP domains on JMP WASH.
  Groups and categories are shown as a percentage of their own maximum, so a
  1-point and an 11-point group share one colour ramp.
- **Markers are binned by quantile**, not by fixed thresholds, so the bins
  always split the health centers actually on screen — change the atoll filter
  and they re-split. Quantiles rank sites against each other, not against a
  target; the legend says so and prints each bin's real range and count. Ties
  are never split across bins, so a heavy tie yields fewer bins than requested
  (a 1-point question group is 0% or 100%, hence two). That is honest, not a
  bug. The JMP tab is the exception: a service ladder is an ordered *category*,
  so each level keeps a fixed colour regardless of who else is on screen.
- The marker ramp is a single hue, light→dark, validated (monotone lightness,
  adjacent ΔL ≥ 0.06, light end 2.42:1 on a light surface, hue spread 4°). It
  is orange rather than the usual sequential blue because every basemap here is
  ocean and blue markers on blue water have no figure/ground separation. There
  is no dark basemap for the same reason the ramp is validated: a dark surface
  needs its own validated steps.
- Basemaps are Esri raster tiles (Ocean, Street, Satellite) — token-free, one
  provider, one attribution. Ocean is the default because it renders
  bathymetry and reef outlines, so RMI's atoll chains read as places rather
  than dots on a wash. The other free raster sources were checked and
  rejected: OpenStreetMap's volunteer servers answer HTTP 418 "Access blocked"
  for a deployed app, and CARTO's raster endpoint now returns an
  "API KEY REQUIRED" tile.

An earlier pass used pydeck/deck.gl. It was replaced because it cannot put
controls *in* the map, and because its declarative JSON cannot supply
`TileLayer`'s `renderSubLayers` callback — raster tiles failed as
`GeoJsonLayer`, which forced a vector basemap, which drew RMI's thin reef
rings sub-pixel, which in turn forced drawing the country's admin polygons as
a separate layer just to make land visible. MapLibre's native raster sources
removed that whole chain.

Note the maps need WebGL. Normal browsers have it; very old ones or
locked-down VDI setups may not.

## Where the data comes from

**The app makes no API calls at runtime.** Every tab reads a JSON file
committed to this repo. That means the deployed instance needs no MIS
credentials, loads in about a second, and keeps serving whether or not the
MIS is reachable.

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
  listing is fetched and shared between the two. The canonical sites in
  `performance_data.json` are matched to that listing **by registration
  name**, with the stored `mis_datapoint_id` only as a fallback — the
  September 2026 migration renumbered every datapoint id (adding
  10,000,000) while leaving names and uuids intact, and an id-only join
  resolved 0 of 18 sites.
- Two guards exist because of that migration, since a broken join produces
  empty output rather than an error: the script **aborts** if no
  registration matches a canonical site, and **refuses** to overwrite a
  snapshot with one containing fewer site-rounds (`--force` overrides, for
  a genuine drop). A failed build exits non-zero and writes nothing.
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

Base URL: `https://mohhs.mis.akvo.org` (the instance moved here from
`mohhs-mis.akvotest.org` in September 2026). **Only the build scripts call
these endpoints** — the dashboard itself never does. All of them go through
`mis_client.py`.

The URL is **not** hardcoded into the call sites: `mis_client.get_base_url()`
resolves it, in order, from the `MIS_BASE_URL` environment variable, then
`st.secrets["mis"]["base_url"]`, then `base_url` in `.env`, then
`DEFAULT_BASE_URL`. It is read per login rather than at import time, and the
resolved value is logged at login so pointing at the wrong instance is
obvious immediately instead of surfacing as a confusing 404. Moving the
instance again is a config change, not a code change.

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
