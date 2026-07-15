"""Performance Assessment tab — score trends (Jul 2025 / Oct 2025 / Feb 2026)
and improvement-plan tracking for the 18 Register=Y health centers.

Reads performance_data.json (built by build_performance_data.py). See
VISUALS.md for what each element below shows and where its data comes from.
"""
import json
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from chart_helpers import FONT_FAMILY, TEXT_GRAY, add_map_legend, apply_chart_theme, build_folium_map, rgba

DATA_PATH = Path(__file__).resolve().parent / "performance_data.json"

ROUND_LABELS = {"2025-07": "July 2025", "2025-10": "Oct 2025", "2026-02": "Feb 2026"}
ROUND_COLORS = {"2025-07": "#bfdbfe", "2025-10": "#60a5fa", "2026-02": "#1d4ed8"}
BAND_GREEN, BAND_AMBER, BAND_RED = "#22a06b", "#f2a93b", "#e5484d"
# folium.Icon only accepts a fixed named-color palette (no arbitrary hex)
MAP_ABOVE, MAP_BELOW = "darkgreen", "red"
# hex equivalents of the above, for the legend swatches (Leaflet.awesome-markers palette)
MAP_ABOVE_HEX, MAP_BELOW_HEX = "#728224", "#D63E2A"


def band_color(score):
    if score is None:
        return "#94a3b8"
    if score >= 55:
        return BAND_GREEN
    if score >= 35:
        return BAND_AMBER
    return BAND_RED


@st.cache_data
def load_data():
    return json.loads(DATA_PATH.read_text())


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
    st.caption("18 health centers · 3 assessment rounds · July 2025 – Feb 2026")

    data = load_data()
    sites = data["sites"]
    median = data["median_latest_score"]  # fixed benchmark over all 18 sites, independent of the filter below

    if "perf_selected_site" not in st.session_state:
        st.session_state.perf_selected_site = max(sites, key=lambda s: s["latest_score"])["site_key"]

    # --------------------------------------------------------- Island filter
    all_atolls = sorted({s["atoll"] for s in sites})
    selected_atolls = st.multiselect(
        "Filter by atoll/island", options=all_atolls, default=all_atolls,
        help="Scopes the ranked chart and map below. The median score line stays fixed to all 18 sites.",
        key="perf_atoll_filter",
    )
    filtered_sites = [s for s in sites if s["atoll"] in selected_atolls]

    if not filtered_sites:
        st.warning("No health centers match the selected filter.")
        st.stop()

    # -------------------------------------------------------------- Map
    st.subheader("Map")
    st.caption(
        f"🏥 colored by whether the Feb 2026 score is above or below the median ({median:.0f}%). "
        "Hover a marker for a quick look, click one to load its plan below. "
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

    m = build_folium_map(gps_sites, marker_color, tooltip, popup)
    add_map_legend(
        m, f"vs. median ({median:.0f}%)",
        [
            (MAP_ABOVE_HEX, f"Above median ({round(100 * n_above / n_total)}%)"),
            (MAP_BELOW_HEX, f"Below median ({round(100 * n_below / n_total)}%)"),
        ],
    )
    map_state = st_folium(m, use_container_width=True, height=560, key="perf_folium_map", returned_objects=["last_object_clicked"])

    clicked = (map_state or {}).get("last_object_clicked")
    if clicked:
        # Folium's click event doesn't carry our site_key through — match the
        # clicked lat/lng back to the site we placed there (exact same floats).
        best = min(gps_sites, key=lambda s: (s["gps"]["lat"] - clicked["lat"]) ** 2 + (s["gps"]["lon"] - clicked["lng"]) ** 2)
        st.session_state.perf_selected_site = best["site_key"]

    st.divider()

    # Chart and detail panel side by side — clicking a bar updates the panel
    # in the same viewport, no scrolling needed to see the effect of the click.
    chart_col, detail_col = st.columns([3, 2], gap="large")

    # ------------------------------------------------------------ Bar chart
    with chart_col:
        st.subheader("Ranked Score Chart")
        show_all_rounds = st.toggle(
            "Show all rounds (July 2025 / Oct 2025 / Feb 2026)", value=False, key="perf_show_all_rounds",
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
                fig.add_trace(
                    go.Bar(
                        name=ROUND_LABELS[r],
                        y=names,
                        x=[s["scores"].get(r, {}).get("overall") for s in plot_order],
                        customdata=hover_meta,
                        orientation="h",
                        marker=dict(color=ROUND_COLORS[r], cornerradius=4),
                        hovertemplate="<b>%{y}</b> — " + ROUND_LABELS[r] + "<br>Score: %{x}%<extra></extra>",
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
            st.caption("🟩 ≥55% &nbsp;&nbsp; 🟨 35–54% &nbsp;&nbsp; 🟥 &lt;35% &nbsp;&nbsp;|&nbsp;&nbsp; ▲▼ = pts vs. baseline round", unsafe_allow_html=True)

        st.caption("👆 Click any bar to load its improvement plan on the right — clicking any of the three rounds selects the same site.")

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
        if st.session_state.perf_selected_site in [s["site_key"] for s in plot_order]:
            sel_idx = [s["site_key"] for s in plot_order].index(st.session_state.perf_selected_site)
            shapes.append(dict(
                type="rect", xref="paper", x0=0, x1=1,
                yref="y", y0=sel_idx - 0.5, y1=sel_idx + 0.5,
                fillcolor="rgba(29,78,216,0.07)", line=dict(width=0), layer="below",
            ))

        apply_chart_theme(
            fig,
            height=650,
            margin=dict(l=10, r=10, t=10, b=10),
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
            if clicked_bar:
                st.session_state.perf_selected_site = clicked_bar[0]

    # -------------------------------------------------------- Detail panel
    with detail_col:
        site_by_key = {s["site_key"]: s for s in sites}
        site_names = {s["site_key"]: s["display_name"] for s in sites}
        ordered_keys = [s["site_key"] for s in sorted(sites, key=lambda s: -s["latest_score"])]

        st.subheader("Improvement Plan detail")
        picked = st.selectbox(
            "Health center (or click a bar on the left)",
            options=ordered_keys,
            format_func=lambda k: f"{site_names[k]} — {site_by_key[k]['latest_score']}%",
            index=ordered_keys.index(st.session_state.perf_selected_site),
            key="perf_site_select",
        )
        st.session_state.perf_selected_site = picked
        selected = site_by_key[st.session_state.perf_selected_site]
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

        st.info(plan["ai_summary"], icon="✨")

        tab_new, tab_status = st.tabs(["Feb 2026 new plan", "Oct 2025 status"])
        with tab_new:
            new_plan = plan.get("2026-02_new_plan")
            if not new_plan:
                st.caption("No Feb 2026 plan recorded for this site.")
            else:
                for cat, cat_label in (("ha", "Health Assistant"), ("local_govt", "Local Government"), ("oihcs", "OIHCS")):
                    entries = new_plan.get(cat) or []
                    if not entries:
                        continue
                    st.markdown(f"_{cat_label}_")
                    for item in entries:
                        st.markdown(f"- {item}")

        with tab_status:
            status = plan.get("2026-02_status")
            if not status:
                st.caption("No Feb 2026 status recorded for this site.")
            else:
                for cat, cat_label in (("ha", "Health Assistant"), ("local_govt", "Local Government"), ("oihcs", "OIHCS")):
                    entries = status.get(cat) or []
                    if not entries:
                        continue
                    st.markdown(f"_{cat_label}_")
                    for e in entries:
                        mark = {"True": "✅", "False": "❌"}.get(str(e["done"]), "❔")
                        st.markdown(f"- {mark} {e['item']}")
