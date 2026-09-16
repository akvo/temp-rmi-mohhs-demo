"""Performance Assessment tab — score trends (Jul 2025 / Oct 2025 / Feb 2026,
plus any newer live round) and improvement-plan tracking for the 18
Register=Y health centers.

The 3 historical rounds always come from the curated performance_data.json
(built by build_performance_data.py) and are never overwritten. On top of
that, newer rounds come from performance_live_data.json — a snapshot of the
MIS written by build_live_data.py and committed to the repo. This tab makes
no API calls at runtime: the deployed instance needs no MIS credentials and
keeps working when the MIS is down. Re-run build_live_data.py and commit to
refresh. A round is shown as soon as any site has reported for it, flagged
"partial" rather than held back until all 18 have.

See VISUALS.md for what each element below shows and where its data comes from.
"""
import calendar
import json
import re
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

import performance_live
from chart_helpers import FONT_FAMILY, TEXT_GRAY, add_map_legend, apply_chart_theme, atoll_multiselect, build_folium_map, rgba

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "performance_data.json"
LIVE_DATA_PATH = HERE / "performance_live_data.json"

ROUND_LABELS = {"2025-07": "July 2025", "2025-10": "Oct 2025", "2026-02": "Feb 2026"}
ROUND_COLORS = {"2025-07": "#bfdbfe", "2025-10": "#60a5fa", "2026-02": "#1d4ed8"}
LIVE_ROUND_COLOR = "#ef4444"
BAND_GREEN, BAND_AMBER, BAND_RED = "#22a06b", "#f2a93b", "#e5484d"
# Score bands. Named so band_color() and the legend caption can never drift
# apart -- the caption is built from these, not retyped.
BAND_GREEN_FROM, BAND_AMBER_FROM = 55, 35
# folium.Icon only accepts a fixed named-color palette (no arbitrary hex)
MAP_ABOVE, MAP_BELOW = "darkgreen", "red"
# hex equivalents of the above, for the legend swatches (Leaflet.awesome-markers palette)
MAP_ABOVE_HEX, MAP_BELOW_HEX = "#728224", "#D63E2A"
MAP_HEIGHT = 560


def round_label(r):
    if r in ROUND_LABELS:
        return ROUND_LABELS[r]
    year, month = r.split("-")
    return f"{calendar.month_name[int(month)]} {year}"


def round_color(r, is_live):
    return LIVE_ROUND_COLOR if is_live else ROUND_COLORS.get(r, "#94a3b8")


def band_color(score):
    if score is None:
        return "#94a3b8"
    if score >= BAND_GREEN_FROM:
        return BAND_GREEN
    if score >= BAND_AMBER_FROM:
        return BAND_AMBER
    return BAND_RED


@st.cache_data
def load_data():
    return json.loads(DATA_PATH.read_text())


@st.cache_data
def load_live_data():
    """The committed MIS snapshot (build_live_data.py), or None if it hasn't
    been built yet — the tab then shows the curated static rounds only,
    which is a perfectly valid dataset, just an older one."""
    if not LIVE_DATA_PATH.exists():
        return None
    return json.loads(LIVE_DATA_PATH.read_text())


def load_merged_performance_data():
    """Static rounds (always present, never modified) + every round in the
    committed MIS snapshot, however partial its site coverage (see
    performance_live's module docstring). Returns (data, has_snapshot) —
    has_snapshot is False when build_live_data.py hasn't been run yet.
    """
    static = load_data()
    live = load_live_data()
    if live is None:
        return static, False
    return performance_live.merge_live_rounds(static, live["rounds"], live["meta"]), True


BREAKDOWN_TRACK = "#eef1f5"  # unscored remainder of each group's bar


def latest_round_with_groups(site, rounds):
    """The most recent round this site has a per-question-group breakdown
    for, or None. Only rounds from the MIS snapshot carry one -- the three
    curated static rounds were transcribed from summary reports that only
    ever had the overall score."""
    return next((r for r in reversed(rounds) if site["scores"].get(r, {}).get("groups")), None)


def render_score_breakdown(site, rounds, group_rounds):
    """Per-question-group breakdown of the site's overall score, from the
    form's own per-group `autofield` score questions. Each row is a group's
    points (colored by the same band thresholds as the overall score) on top
    of a track the full width of that group's maximum, so a short colored bar
    against a long track reads directly as "this is where the points went"."""
    round_key = latest_round_with_groups(site, rounds)
    if round_key is None:
        since = f", which start from the {round_label(group_rounds[0])} round" if group_rounds else ""
        st.caption(
            "No per-group score breakdown for this health center — it is only recorded "
            f"on MIS submissions{since}."
        )
        return

    round_scores = site["scores"][round_key]
    groups = round_scores["groups"]
    all_groups = performance_live.SCORE_GROUPS
    rows = [g for g in all_groups if g["key"] in groups]
    points = round_scores.get("points", sum(groups[g["key"]] for g in rows))

    subtitle = f"{points} of {performance_live.TOTAL_MAX_POINTS} points ({round_scores['overall']}%)"
    if len(rows) < len(all_groups):
        subtitle += f" — only {len(rows)} of {len(all_groups)} question groups recorded"
    st.markdown(
        f"**Score breakdown — {round_label(round_key)}**  \n"
        f"<span style='color:{TEXT_GRAY}; font-size:0.88rem;'>{subtitle}</span>",
        unsafe_allow_html=True,
    )

    plot_order = list(reversed(rows))  # Plotly draws the first category at the bottom
    names = [g["short"] for g in plot_order]
    scored = [groups[g["key"]] for g in plot_order]
    missed = [g["max_points"] - groups[g["key"]] for g in plot_order]
    colors = [band_color(100 * groups[g["key"]] / g["max_points"]) for g in plot_order]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=names, x=scored, orientation="h", marker=dict(color=colors, cornerradius=3),
        customdata=[[g["label"], g["max_points"]] for g in plot_order],
        hovertemplate="<b>%{customdata[0]}</b><br>Scored: %{x} of %{customdata[1]} points<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=names, x=missed, orientation="h", marker=dict(color=BREAKDOWN_TRACK, cornerradius=3),
        customdata=[[g["label"], g["max_points"]] for g in plot_order],
        hovertemplate="<b>%{customdata[0]}</b><br>Missed: %{x} of %{customdata[1]} points<extra></extra>",
    ))

    max_points = max(g["max_points"] for g in plot_order)
    apply_chart_theme(
        fig,
        barmode="stack",
        bargap=0.34,
        height=42 + 30 * len(plot_order),
        margin=dict(l=10, r=10, t=6, b=6),
        showlegend=False,
        dragmode=False,
        xaxis=dict(range=[0, max_points * 1.3], fixedrange=True, showgrid=False, zeroline=False, visible=False),
        yaxis=dict(automargin=True, fixedrange=True, showgrid=False, ticksuffix="  ", tickfont=dict(size=12)),
        annotations=[
            dict(
                x=max_points * 1.04, y=g["short"], xref="x", yref="y",
                text=f"{groups[g['key']]}/{g['max_points']}", showarrow=False,
                xanchor="left", font=dict(size=11.5, color=c, family=FONT_FAMILY),
            )
            for g, c in zip(plot_order, colors)
        ],
    )
    st.plotly_chart(fig, key="perf_breakdown_chart", width="stretch",
                    config={"displayModeBar": False, "scrollZoom": False})


PLAN_SECTION_KEY = re.compile(r"^(\d{4}-\d{2})_(.+)$")


def plan_sections(sites):
    """{suffix: (round_key, data_key)} for the improvement-plan sections
    present in the data, e.g. {"new_plan": ("2026-02", "2026-02_new_plan")}.

    The round each section belongs to is read off its own key rather than
    written into the UI, so when a newer plan is graduated into the curated
    baseline the tab relabels itself instead of quietly showing last
    round's heading over this round's content."""
    found = {}
    for site in sites:
        for key in site.get("improvement_plan", {}):
            m = PLAN_SECTION_KEY.match(key)
            if m and m.group(2) not in found:
                found[m.group(2)] = (m.group(1), key)
    return found


def improvement_text(site):
    pts = site["improvement_pts"]
    if pts is None:
        return "no baseline to compare"
    if pts > 0:
        return f"▲ +{pts} pts since {site['baseline_round']}"
    if pts < 0:
        return f"▼ {pts} pts since {site['baseline_round']}"
    return f"● no change since {site['baseline_round']}"


def render_performance_tab():
    st.title("NI Health Center Performance")

    data, has_snapshot = load_merged_performance_data()
    sites = data["sites"]
    median = data["median_latest_score"]  # fixed benchmark over every site, independent of the filter below
    round_source = data.get("round_source", {r: "static" for r in data["rounds"]})
    latest_round = data["rounds"][-1]
    # Rounds that carry a per-question-group breakdown (MIS snapshot rounds
    # only) -- read off the data so the "no breakdown" note can name the real
    # first one instead of a round hardcoded when this was written.
    group_rounds = sorted({r for s in sites for r in data["rounds"] if s["scores"].get(r, {}).get("groups")})

    st.caption(
        f"{len(sites)} health centers · {len(data['rounds'])} assessment rounds · "
        f"{round_label(data['rounds'][0])} – {round_label(data['rounds'][-1])}"
    )
    if not has_snapshot:
        st.warning(
            "No MIS snapshot has been built — showing the curated static rounds only. "
            "Run `python3 build_live_data.py` and commit the result to include newer rounds.",
            icon="⚠️",
        )

    # The selectbox's own widget key IS the selection state -- a keyed widget
    # restores its stored value on every rerun and ignores `index`, so a
    # separate state variable gets overwritten by the stale widget value the
    # moment the selectbox is drawn, and map/bar clicks silently do nothing.
    # The map and the chart both run before the selectbox is instantiated,
    # which is what makes assigning to its key legal.
    if st.session_state.get("perf_site_select") not in {s["site_key"] for s in sites}:
        st.session_state.perf_site_select = max(sites, key=lambda s: s["latest_score"])["site_key"]

    # --------------------------------------------------------- Island filter
    all_atolls = sorted({s["atoll"] for s in sites})
    selected_atolls = atoll_multiselect(
        "Filter by atoll/island", all_atolls, key="perf_atoll_filter",
        help=f"Scopes the ranked chart and map below. The median score line stays fixed to all {len(sites)} sites.",
    )
    filtered_sites = [s for s in sites if s["atoll"] in selected_atolls]

    if not filtered_sites:
        st.warning("No health centers match the selected filter.")
        st.stop()

    # -------------------------------------------------------------- Map
    st.subheader("Map")
    st.caption(
        f"🏥 colored by whether the {round_label(latest_round)} score is above or below the "
        f"median ({median:.0f}%). Hover a marker for a quick look, click one to load its plan below. "
        "Use the layer control (top right) to switch basemap, or the +/- to zoom."
    )

    gps_sites = [s for s in filtered_sites if s["gps"]]

    def marker_color(s):
        return MAP_ABOVE if s["above_median"] else MAP_BELOW if s["above_median"] is False else "gray"

    def tooltip(s):
        return f"{s['display_name']} — {s['latest_score']}%"

    def popup(s):
        who = " & ".join(x for x in (s["officers"].get("mayor"), s["officers"].get("ha")) if x)
        band = "above" if s["above_median"] else "below" if s["above_median"] is False else "n/a vs."
        return (
            f"<b>{s['display_name']}</b><br>{who}<br>"
            f"Score: {s['latest_score']}% ({band} median)<br>{improvement_text(s)}"
        )

    n_above = sum(1 for s in gps_sites if s["above_median"])
    n_below = sum(1 for s in gps_sites if s["above_median"] is False)
    n_total = len(gps_sites) or 1  # guard div-by-zero; gps_sites is never empty in practice

    m, view = build_folium_map(gps_sites, marker_color, tooltip, popup, height_px=MAP_HEIGHT)
    add_map_legend(
        m, f"vs. median ({median:.0f}%)",
        [
            (MAP_ABOVE_HEX, f"Above median ({round(100 * n_above / n_total)}%)"),
            (MAP_BELOW_HEX, f"Below median ({round(100 * n_below / n_total)}%)"),
        ],
    )
    map_state = st_folium(
        m, use_container_width=True, height=MAP_HEIGHT, key="perf_folium_map",
        center=view["center"], zoom=view["zoom"],  # required for the fit to stick -- see fit_zoom
        returned_objects=["last_object_clicked"],
    )

    clicked = (map_state or {}).get("last_object_clicked")
    if clicked:
        # Folium's click event doesn't carry our site_key through — match the
        # clicked lat/lng back to the site we placed there (exact same floats).
        best = min(gps_sites, key=lambda s: (s["gps"]["lat"] - clicked["lat"]) ** 2 + (s["gps"]["lon"] - clicked["lng"]) ** 2)
        st.session_state.perf_site_select = best["site_key"]

    st.divider()

    # Chart and detail panel side by side — clicking a bar updates the panel
    # in the same viewport, no scrolling needed to see the effect of the click.
    chart_col, detail_col = st.columns([3, 2], gap="large")

    # ------------------------------------------------------------ Bar chart
    with chart_col:
        st.subheader("Ranked Score Chart")
        show_all_rounds = st.toggle(
            f"Show all rounds ({' / '.join(round_label(r) for r in data['rounds'])})",
            value=False, key="perf_show_all_rounds",
        )

        plot_order = sorted(filtered_sites, key=lambda s: s["latest_score"])  # ascending -> highest ends up on top
        names = [s["display_name"] for s in plot_order]
        hover_meta = [
            [s["site_key"], " & ".join(x for x in (s["officers"].get("mayor"), s["officers"].get("ha")) if x), improvement_text(s)]
            for s in plot_order
        ]

        # Plotly's default click-to-select dims every point not in the current
        # selection ("unselected" opacity ~0.3), with no built-in way to clear
        # it by clicking away. We don't want per-bar dimming at all — selection
        # state is tracked in st.session_state and shown via the row highlight
        # below — so every trace explicitly pins selected/unselected opacity to 1.
        no_dim = dict(selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)))

        fig = go.Figure()
        if show_all_rounds:
            for r in data["rounds"]:
                is_live = round_source.get(r) == "live"
                fig.add_trace(
                    go.Bar(
                        name=round_label(r),
                        y=names,
                        x=[s["scores"].get(r, {}).get("overall") for s in plot_order],
                        customdata=hover_meta,
                        orientation="h",
                        marker=dict(color=round_color(r, is_live), cornerradius=4),
                        hovertemplate="<b>%{y}</b> — " + round_label(r) + "<br>Score: %{x}%<extra></extra>",
                        **no_dim,
                    )
                )
            fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.12)
        else:
            fig.add_trace(
                go.Bar(
                    y=names,
                    x=[s["latest_score"] for s in plot_order],
                    customdata=hover_meta,
                    orientation="h",
                    marker=dict(color=[band_color(s["latest_score"]) for s in plot_order], cornerradius=6),
                    text=[f"{s['latest_score']}%" for s in plot_order],
                    textposition="outside",
                    textfont=dict(size=13, color=TEXT_GRAY),
                    cliponaxis=False,
                    hovertemplate=(
                        "<b>%{y}</b><br>%{customdata[1]}<br>Score: %{x}%<br>%{customdata[2]}<extra></extra>"
                    ),
                    **no_dim,
                )
            )
            fig.update_layout(bargap=0.35)
            st.caption(
                f"🟩 ≥{BAND_GREEN_FROM}% &nbsp;&nbsp; 🟨 {BAND_AMBER_FROM}–{BAND_GREEN_FROM - 1}% "
                f"&nbsp;&nbsp; 🟥 &lt;{BAND_AMBER_FROM}% &nbsp;&nbsp;|&nbsp;&nbsp; "
                "▲▼ = pts vs. baseline round",
                unsafe_allow_html=True,
            )

        st.caption("👆 Click any bar to load its score breakdown and improvement plan on the right — clicking any round selects the same site.")

        # progress-since-baseline bubble, one per site, in its own fixed-position
        # column to the right of the bars so they line up regardless of bar length
        badge_x = 122
        badges = []
        for s in plot_order:
            pts = s["improvement_pts"]
            if pts is None:
                text, color = "no baseline", "#94a3b8"
            elif pts > 0:
                text, color = f"▲ +{pts}", BAND_GREEN
            elif pts < 0:
                text, color = f"▼ {pts}", BAND_RED
            else:
                text, color = "● +0", "#94a3b8"
            badges.append(dict(
                x=badge_x, y=s["display_name"], xref="x", yref="y",
                text=text, showarrow=False, xanchor="left", align="left",
                font=dict(size=11, color=color, family=FONT_FAMILY),
                bgcolor=rgba(color, 0.12), bordercolor=rgba(color, 0.35), borderwidth=1, borderpad=4,
            ))

        # Highlight the currently selected HC's whole row (all rounds together
        # in grouped mode) with a background band, driven purely by
        # session_state — not Plotly's selection state — so it stays correct
        # whether the site was picked by clicking a bar or via the selectbox
        # below, and never "sticks".
        shapes = []
        if st.session_state.perf_site_select in [s["site_key"] for s in plot_order]:
            sel_idx = [s["site_key"] for s in plot_order].index(st.session_state.perf_site_select)
            shapes.append(dict(
                type="rect", xref="paper", x0=0, x1=1,
                yref="y", y0=sel_idx - 0.5, y1=sel_idx + 0.5,
                fillcolor="rgba(29,78,216,0.07)", line=dict(width=0), layer="below",
            ))

        apply_chart_theme(
            fig,
            height=650,
            # b leaves room for the x-axis title below the tick labels;
            # at the default 10 the two overlap.
            margin=dict(l=10, r=10, t=10, b=48),
            xaxis=dict(
                title="Score (%)", range=[0, 145], fixedrange=True,
                showgrid=True, gridcolor="#eef1f5", zeroline=False,
            ),
            yaxis=dict(automargin=True, fixedrange=True, showgrid=False, ticksuffix="  "),
            dragmode=False,
            showlegend=show_all_rounds,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
            annotations=badges,
            shapes=shapes,
        )

        event = st.plotly_chart(
            fig, on_select="rerun", key="perf_score_chart", width="stretch",
            config={"displayModeBar": False, "scrollZoom": False},
        )
        if event and event.selection and event.selection.get("points"):
            clicked_bar = event.selection["points"][0].get("customdata")
            if clicked_bar and clicked_bar[0] != st.session_state.perf_site_select:
                st.session_state.perf_site_select = clicked_bar[0]
                st.rerun()  # redraw the detail panel, which this run already passed

    # -------------------------------------------------------- Detail panel
    with detail_col:
        site_by_key = {s["site_key"]: s for s in sites}
        site_names = {s["site_key"]: s["display_name"] for s in sites}
        ordered_keys = [s["site_key"] for s in sorted(sites, key=lambda s: -s["latest_score"])]

        st.subheader("Health center detail")
        picked = st.selectbox(
            "Health center (or click a bar on the left)",
            options=ordered_keys,
            format_func=lambda k: f"{site_names[k]} — {site_by_key[k]['latest_score']}%",
            key="perf_site_select",  # no `index`: the key above is the state
        )
        selected = site_by_key[picked]
        plan = selected["improvement_plan"]

        score_color = band_color(selected["latest_score"])
        who = " & ".join(x for x in (selected["officers"].get("mayor"), selected["officers"].get("ha")) if x)
        st.markdown(
            f"""
            <div style="display:flex; align-items:baseline; flex-wrap:wrap; gap:0.5rem; margin-top:0.2rem;">
              <span style="font-size:1.25rem; font-weight:600;">{selected['display_name']}</span>
              <span style="background:{score_color}22; color:{score_color}; font-weight:600;
                           padding:2px 10px; border-radius:999px; font-size:0.85rem;">
                {selected['latest_score']}%
              </span>
            </div>
            <div style="color:{TEXT_GRAY}; font-size:0.9rem; margin-bottom:0.5rem;">{who}</div>
            """,
            unsafe_allow_html=True,
        )

        render_score_breakdown(selected, data["rounds"], group_rounds)

        st.info(plan["ai_summary"], icon="✨")

        sections = plan_sections(sites)
        new_round, new_key = sections.get("new_plan", (None, None))
        status_round, status_key = sections.get("status", (None, None))
        actions_round, _ = sections.get("actions", (None, None))

        new_tab_label = f"{round_label(new_round)} new plan" if new_round else "New plan"
        # The status section records how the *previous* round's plan was doing
        # when the later round assessed it, so its label names both rounds --
        # the old fixed "Oct 2025 status" labelled Feb 2026 content.
        status_tab_label = (
            f"{round_label(actions_round)} plan status"
            if actions_round else (f"{round_label(status_round)} status" if status_round else "Plan status")
        )

        tab_new, tab_status = st.tabs([new_tab_label, status_tab_label])
        with tab_new:
            new_plan = plan.get(new_key) if new_key else None
            if not new_plan:
                st.caption(f"No {new_tab_label.lower()} recorded for this site.")
            else:
                for cat, cat_label in (("ha", "Health Assistant"), ("local_govt", "Local Government"), ("oihcs", "OIHCS")):
                    entries = new_plan.get(cat) or []
                    if not entries:
                        continue
                    st.markdown(f"_{cat_label}_")
                    for item in entries:
                        st.markdown(f"- {item}")

        with tab_status:
            status = plan.get(status_key) if status_key else None
            if actions_round and status_round:
                st.caption(
                    f"Where the {round_label(actions_round)} improvement plan stood when it was "
                    f"assessed at {round_label(status_round)}."
                )
            if not status:
                st.caption(f"No {status_tab_label.lower()} recorded for this site.")
            else:
                for cat, cat_label in (("ha", "Health Assistant"), ("local_govt", "Local Government"), ("oihcs", "OIHCS")):
                    entries = status.get(cat) or []
                    if not entries:
                        continue
                    st.markdown(f"_{cat_label}_")
                    for e in entries:
                        mark = {"True": "✅", "False": "❌"}.get(str(e["done"]), "❔")
                        st.markdown(f"- {mark} {e['item']}")
