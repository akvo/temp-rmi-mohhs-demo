# Visual-by-visual reference

> **No round names, thresholds or counts are hardcoded in the UI.** Every
> caption, legend, tab label and axis title is built from the data it
> describes — the round being colored, the band constants, the section and
> domain labels in the source file. Change the data and the sub-text
> follows. This is deliberate: the map caption used to read "Feb 2026" long
> after it had started coloring by July 2026, and the improvement-plan tab
> read "Oct 2025 status" over Feb 2026 content.

Every chart/panel in all three tabs, what it shows, where its data comes
from, and what processing (if any) was applied between the raw source and
the field the UI reads. For the two tabs backed by a committed snapshot,
"Processing" describes what already happened in the `build_*.py` ETL script
— the Streamlit code only does display-time formatting (sorting, coloring,
number formatting), not data transformation, unless noted. The Essential
Meds tab has no ETL script: its shaping happens at fetch time in
`meds_live.py`, and is described in that tab's own section.

---

## Tab 1 — Performance Assessment (`performance_tab.py`)

### Island/atoll filter

- **Shows**: a multiselect of all 18 atolls; scopes the map and ranked
  chart below.
- **Data source**: `performance_data.json` → `sites[].atoll`.
- **Processing**: none. Pure UI filter — doesn't affect the median (see
  Map, below).

### Map

- **Shows**: one pin per filtered site, colored by whether its Feb 2026
  score is above or below the median; hover for a one-line summary, click
  for a fuller popup, click also loads that site into the detail panel. A
  color-key legend ("Above median" / "Below median") floats in the bottom
  right of the map.
- **Data source**: `sites[].gps` (`lat`/`lon`/`source`) and
  `sites[].above_median`.
- **Processing**:
  - GPS: primary source is the live MIS registration (form `1783289494205`
    `geo` field). 4 of the 18 registrations have no GPS on the platform
    (Wotje, Mejit, Maloelap-Kaben, Aur-Tabal) — those fall back to the
    named ADM2 centroid in `admin_data.geojson`. `gps.source` records which
    one was used per site.
  - `above_median`: computed once in the ETL as `latest_score >
    median_latest_score`, where the median is over **all 18 sites**
    regardless of the current filter — so narrowing the filter changes
    which markers are visible, not what "above/below" means.
  - Popup text also includes the improvement-vs-baseline line — see
    "Improvement badge" below for how that's computed.

### Ranked Score Chart

- **Shows**: horizontal bars, one per filtered site, sorted by latest
  score descending, colored green (≥55%) / amber (35–54%) / red (<35%). A
  toggle switches to a grouped view showing July 2025 / Oct 2025 / Feb 2026
  side by side per site.
- **Data source**: `sites[].scores["2025-07"|"2025-10"|"2026-02"].overall`,
  `sites[].latest_score`.
- **Processing**:
  - July/Oct 2025 scores: extracted from
    `raw_sources/NI Health Center Performance Results....xlsx`, sheets
    `Main HC July 2025 Scores` (column "OVERALL SCORES") and
    `All HC Overall Scores` (the column dated 2025-10-01) respectively,
    matched to a site via an HC-name keyword lookup (`HC_KEYWORD_TO_SITE`
    in `build_performance_data.py`) since the sheets' row layout doesn't
    align 1:1 with the canonical site list.
  - Feb 2026 scores: **no machine-readable source** — hand-transcribed
    from a chart screenshot into the `FEB_2026_SCORES` dict. Cross-checked
    at build time: the script recomputes July/Oct averages from its own
    extraction and prints them next to the workbook's own printed
    aggregate (`Performance Trends Line Graph` sheet) so a mismatch is
    visible immediately.
  - 3 sites (Mili, Arno, Maloelap) have no July 2025 figure in the source
    workbook at all — their bars in the grouped view simply have no July
    segment, and their baseline (see below) falls back to Oct 2025.
  - Color bands are a display-time threshold (≥55/35–54/<35), not stored
    in the JSON.

### Improvement badge (▲/▼ pts)

- **Shows**: a small colored badge next to each bar/row, e.g. `▲ +12` or
  `▼ −4`, and the equivalent sentence in map popups/hover.
- **Data source**: `sites[].improvement_pts`, `sites[].baseline_round`.
- **Processing**: `latest_score − baseline_score`, where `baseline_round`
  is the **earliest round with any data for that site** — July 2025 for
  15 sites, Oct 2025 for the 3 that have no July figure (see above). It is
  *not* always "vs. July 2025".

### Score breakdown (detail panel)

- **Shows**: for the selected site, how its overall score splits across the
  assessment form's nine scored question groups — one row per group, the
  points scored (colored by the same ≥55 / 35–54 / <35 percent-of-max bands
  as the overall score) drawn on a track the full width of that group's
  maximum, with `scored/max` alongside. A short colored bar against a long
  track reads directly as "this is where the points went". Header line gives
  the round and the total, e.g. "37 of 48 points (77%)".
- **Data source**: `sites[].scores[round].groups` + `.points` + `.overall`,
  from `performance_live_data.json` (built by `performance_live.fetch_live_rounds`).
- **Processing**: none — each group's points come straight from that group's
  own `autofield` "... Score" question on the submission, and the total from
  `final_score` / `overall_score_in_out_of_48`. The per-group **maxima** are
  the one derived part (`performance_live.SCORE_GROUPS`): the API exposes no
  per-option scores, so they are counted from each group's scoring questions
  (1 point per `yes`, 1 per selected multiple-option value excluding the
  non-scoring `none`/`other`). That rule reproduces every group score and
  `final_score` exactly across all 16 July 2026 submissions, and the maxima
  sum to the form's own denominator of 48.
- **Only MIS-snapshot rounds have this.** The three curated static rounds were
  transcribed from summary reports carrying overall scores only, so the panel
  shows an explanatory caption instead for a site with no MIS submission.

### Improvement Plan detail panel

- **Shows**: the selected site's name/score/officers, a one-paragraph
  summary, and two tabs — "Feb 2026 new plan" and "Oct 2025 status" — each
  broken out by Health Assistant / Local Government / OIHCS.
- **Data source**: `sites[].improvement_plan` (`2025-10_actions`,
  `2026-02_status`, `2026-02_new_plan`, `ai_summary`).
- **Processing**:
  - `2025-10_actions`: parsed from the xlsx's `Oct2025 Improvemt Plans`
    sheet, one row per site, split into a list per numbered action item.
  - `2026-02_status`: parsed from
    `raw_sources/NI HC Oct-Nov 2025 MEC Improvement Results to Feb 2026.docx`'s
    table — each action item's trailing "- Yes"/"- No" is extracted via
    regex into `{"item": ..., "done": true|false|null}`. **Two sites
    (Ebon, Namdrik) have this field empty** — their rows in the source doc
    were found to duplicate other sites' text verbatim; see README's Known
    Limitations. The underlying flag is in `data_quality_note` on those
    site records (not shown in the UI).
  - `2026-02_new_plan`: parsed from
    `raw_sources/NI HC Improvement Plans-All Sites (Feb 2026).docx`'s
    table. The source document is bilingual (English + Marshallese); the
    Marshallese translation block (everything after a `Majol` line) is
    stripped, English-only text is kept.
  - `ai_summary`: **not a live LLM call** — a template computed once at
    ETL build time from the two fields above: a count of completed vs.
    total Oct-2025 action items with a recorded status, plus the first 2
    items from the new Feb 2026 plan as "top priorities". Deterministic
    and reproducible, no API dependency at dashboard runtime.

---

## Tab 2 — Essential Meds & Supplies (`meds_tab.py`)

Source: `meds_data.json`, a committed snapshot of form `1783385736711`
("NI HC - Essential Meds and Supplies Checklist") written by
`build_live_data.py` — see README's "Where the data comes from". The tab
makes no API calls.

**How the scores work.** The checklist is two independently scored sections
of "tick what you have in stock" multiple-option categories: Essential
Supplies (7 categories, 52 items) and Essential Meds (22 categories, 60
items). Each section has its own `*_score` and `*_percentage` autofield.
`none` and `other` are bookkeeping choices, not stocked items, and are
excluded from both the score and the maximum — counting one point per
remaining ticked item reproduces every `*_score` autofield exactly, and the
resulting maxima (52 / 60) reproduce every `*_percentage` autofield as
`round(100 * score / max)`, verified across all scored submissions on the
form. The category structure, item labels and maxima are **derived from the
published form definition at build time**, not hardcoded.

**Bands.** `GOOD_FROM` / `PARTIAL_FROM` in `meds_tab.py` (currently 80 / 50)
are a *dashboard reading aid, not an MOHHS target*: unlike the Performance Assessment (which defines >85% in its
own `meets_target` field), this form sets no threshold, so there was none to
honour. They are labelled as such in the UI.

### KPI row

- **Shows**: health centers reporting, average essential-meds and
  essential-supplies availability, and how many sites clear 80% on both.
- **Processing**: plain means over the filtered, reporting sites. The two
  sections are deliberately never averaged together — a site can be well
  stocked on equipment and out of medicines, and one combined number would
  hide exactly that.

### Map

- **Shows**: 🏥 per health center, colored by essential-meds availability.
  Hover gives both section scores; clicking loads that site's checklist.
- **Data source**: `sections.meds.pct`, plus GPS from the shared site
  registry (`performance_data.json`'s `sites[]`, reused so a health center
  is named and placed identically on every tab).

### Stock availability by health center

- **Shows**: grouped horizontal bars, essential meds and essential supplies
  side by side per site, sorted by meds availability. Clicking a bar loads
  that site on the right; the selected row is highlighted.
- **Data source**: `sections[*].pct`, with `score`/`max` in the hover.

### Most commonly out of stock

- **Shows**: the 12 individual items missing at the most health centers,
  bar colored by which section the item belongs to.
- **Processing**: counted client-side across the *filtered* sites reporting
  in the selected round — an item counts as missing when its option value
  is absent from that site's ticked list for its category.

### Checklist detail panel

- **Shows**: the selected site's two section score cards, then a tab per
  section containing a per-category breakdown (items in stock on a track
  the full width of that category's item count, same idiom as the
  Performance tab's score breakdown) and an "Out of stock" expander listing
  the specific missing items, grouped by category.
- **Processing**: missing = the category's schema items minus the ticked
  ones. Ticked values the form no longer offers are dropped on ingest, so
  that difference is always clean.
- A submission that predates the form's score autofields gets its score
  recounted from the ticked items, and the panel says so.
- A submission filed under an inferred round says so in the panel, naming
  the form date it was inferred from. Round coverage and anything excluded
  are reported by `build_live_data.py` at build time rather than in the UI.

## Tab 3 — JMP WASH Facility Assessment (`jmp_wash_tab.py`)

### Atoll filter

- **Shows**: a multiselect of atolls with a JMP assessment on file; scopes
  everything below except nothing is held fixed like the Performance tab's
  median (there's no cross-filter benchmark here).
- **Data source**: `jmp_data.json` → `sites[].atoll`.
- **Processing**: `atoll` comes from resolving each JMP submission's
  `administration` id via `GET /api/v1/administration/<id>` and splitting
  its `full_name` (pipe-separated hierarchy) — done once in
  `build_jmp_data.py`, not at dashboard runtime.

### KPI row (4 metrics)

- **Shows**: facilities assessed, % meeting full JMP basic WASH, % with
  basic water service, atolls covered — all over the **currently
  filtered** set.
- **Data source**: aggregated client-side in `jmp_wash_tab.py` from
  `sites[].meets_jmp_basic_wash` and `sites[].levels.water`.
- **Processing**: simple counts/percentages recomputed on every rerun from
  whatever `filtered_sites` currently is — nothing pre-aggregated in the
  JSON, so these numbers always match the current filter exactly.

### Map

- **Shows**: one pin per filtered site, colored by the JMP service level
  (Basic/Limited/No service) for whichever domain is picked in the "Color
  map by" dropdown above it. Hover/click same as the Performance tab's map.
  A color-key legend (Basic/Limited/No Service, titled with the selected
  domain's question text) floats in the bottom right of the map and
  updates as the domain selection changes.
- **Data source**: `sites[].levels[domain]`, `sites[].gps`.
- **Processing**: `levels` are computed once in `build_jmp_data.py` from
  the raw form answers — see **JMP_SCORING.md** for the exact per-domain
  formula (water, sanitation, hygiene, health-care waste, environmental
  cleaning), each ported line-for-line from the form's own validated
  autofield engine formulas. GPS: live MIS `geo` field, falling back to
  `GPS_FALLBACK` (hardcoded coordinates) for 3 pre-existing registrations
  that predate this project's GPS-on-registration convention.

### Service levels by domain (5 small bar charts)

- **Shows**: for each of the 5 JMP domains, a 100%-stacked-style bar
  showing what fraction of filtered sites are Basic/Limited/No service.
- **Data source**: `sites[].levels[domain]`, aggregated.
- **Processing**: counts/percentages computed client-side from the
  filtered site list on every rerun (same pattern as the KPI row) — not
  pre-aggregated in the JSON.

### Facility detail panel

- **Shows**: the selected facility's name/atoll/island, an overall
  "meets/doesn't meet full JMP basic WASH" badge, a per-domain level badge
  row, and an expander with every raw form answer.
- **Data source**: `sites[].levels`, `sites[].meets_jmp_basic_wash`,
  `sites[].answers`.
- **Processing**: `meets_jmp_basic_wash` is `all(level == "Basic service"
  for level in levels.values())`, computed once in the ETL. `answers` is
  the raw per-question value from the MIS record (question ids mapped back
  to short variable names like `G-W1` via the `QID` dict in
  `build_jmp_data.py`) — shown completely unprocessed, for auditing against
  the computed levels above it.
