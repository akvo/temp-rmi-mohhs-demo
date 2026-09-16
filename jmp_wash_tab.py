"""JMP WASH Facility Assessment tab.

This was a one-time facility assessment, not an ongoing monitoring round
like Performance Assessment -- the underlying MIS submissions aren't
expected to change, so this tab reads the committed jmp_data.json snapshot
directly (built by build_jmp_data.py) rather than fetching live at runtime.
If the assessment is ever redone or corrected, re-run build_jmp_data.py to
regenerate the snapshot and commit the new file. See VISUALS.md for what
each element below shows and where its data comes from.

Colors intentionally differ from the Performance tab's green/amber/red score
bands: this is a 3-level service *ladder* (Basic/Limited/No service), not a
% score, so it uses a blue/amber/orange scheme instead.
"""
import json
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from chart_helpers import TEXT_GRAY, add_map_legend, apply_chart_theme, atoll_multiselect, build_folium_map, rgba

DATA_PATH = Path(__file__).resolve().parent / "jmp_data.json"

LEVEL_COLOR = {"Basic service": "#2a78d6", "Limited service": "#eda100", "No service": "#eb6834"}
LEVEL_TEXT = {"Basic service": "#ffffff", "Limited service": "#241a00", "No service": "#ffffff"}
LEVEL_SHORT = {"Basic service": "Basic", "Limited service": "Limited", "No service": "No Service"}
# Emoji swatch per level, for the legend caption -- built from the data's own
# level list rather than a retyped string, so a level added to or renamed in
# jmp_data.json shows up in the legend instead of silently going missing.
LEVEL_SWATCH = {"Basic service": "🟦", "Limited service": "🟨", "No service": "🟧"}
# folium.Icon only accepts a fixed named-color palette (no arbitrary hex) —
# closest named colors to the LEVEL_COLOR hex scheme above.
LEVEL_MAP_COLOR = {"Basic service": "blue", "Limited service": "orange", "No service": "red"}
# hex equivalents of the above, for the legend swatches (Leaflet.awesome-markers palette)
LEVEL_MAP_COLOR_HEX = {"Basic service": "#38AADD", "Limited service": "#F69730", "No service": "#D63E2A"}
MAP_HEIGHT = 520


@st.cache_data
def load_jmp_data():
    return json.loads(DATA_PATH.read_text())


def render_jmp_wash_tab():
    st.title("JMP WASH Facility Assessment")

    data = load_jmp_data()
    sites = data["sites"]

    st.caption(f"{len(sites)} health centers · JMP-2018 core WASH-in-HCF indicators")
    domains = data["domains"]  # [{key, label, question}, ...]
    levels = data["levels"]    # ["Basic service", "Limited service", "No service"]

    if "jmp_selected_site" not in st.session_state:
        st.session_state.jmp_selected_site = sites[0]["uuid"]

    # --------------------------------------------------------- Atoll filter
    all_atolls = sorted({s["atoll"] for s in sites})
    selected_atolls = atoll_multiselect(
        "Filter by atoll", all_atolls, key="jmp_atoll_filter",
        help="Scopes the map and domain charts below.",
    )
    filtered_sites = [s for s in sites if s["atoll"] in selected_atolls]

    if not filtered_sites:
        st.warning("No health centers match the selected filter.")
        st.stop()

    # ------------------------------------------------------------- KPI row
    total = len(filtered_sites)
    meets_all = sum(1 for s in filtered_sites if s["meets_jmp_basic_wash"])
    basic_water = sum(1 for s in filtered_sites if s["levels"]["water"] == "Basic service")
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Facilities assessed", total)
    kpi_cols[1].metric("Meet full JMP basic WASH", f"{round(meets_all / total * 100)}%", f"{meets_all} of {total}")
    kpi_cols[2].metric("Basic water service", f"{round(basic_water / total * 100)}%", f"{basic_water} of {total}")
    kpi_cols[3].metric("Atolls covered", len({s["atoll"] for s in filtered_sites}))

    st.divider()

    # -------------------------------------------------------------- Map
    st.subheader("Map")
    domain_keys = [d["key"] for d in domains]
    domain_labels = {d["key"]: d["question"] for d in domains}
    map_domain = st.selectbox(
        "Color map by", options=domain_keys, format_func=lambda k: domain_labels[k], key="jmp_map_domain",
    )
    st.caption(
        "🏥 colored by JMP service level for the selected domain. Hover a marker for detail, click one to load it below. "
        "Use the layer control (top right) to switch basemap, or the +/- to zoom."
    )

    def marker_color(s):
        return LEVEL_MAP_COLOR[s["levels"][map_domain]]

    def tooltip(s):
        return f"{s['name']} — {LEVEL_SHORT[s['levels'][map_domain]]}"

    def popup(s):
        lines = "<br>".join(f"{d['label']}: {LEVEL_SHORT[s['levels'][d['key']]]}" for d in domains)
        return f"<b>{s['name']}</b><br>{s['atoll']} — {s['island']}<br>{lines}"

    n_total = len(filtered_sites) or 1  # guard div-by-zero; filtered_sites is never empty here
    level_counts = {l: sum(1 for s in filtered_sites if s["levels"][map_domain] == l) for l in levels}

    m, view = build_folium_map(filtered_sites, marker_color, tooltip, popup, height_px=MAP_HEIGHT)
    add_map_legend(
        m, domain_labels[map_domain],
        [
            (LEVEL_MAP_COLOR_HEX[l], f"{LEVEL_SHORT[l]} ({round(100 * level_counts[l] / n_total)}%)")
            for l in levels
        ],
    )
    map_state = st_folium(
        m, use_container_width=True, height=MAP_HEIGHT, key="jmp_folium_map",
        center=view["center"], zoom=view["zoom"],  # required for the fit to stick -- see fit_zoom
        returned_objects=["last_object_clicked"],
    )

    clicked = (map_state or {}).get("last_object_clicked")
    if clicked:
        best = min(filtered_sites, key=lambda s: (s["gps"]["lat"] - clicked["lat"]) ** 2 + (s["gps"]["lon"] - clicked["lng"]) ** 2)
        st.session_state.jmp_selected_site = best["uuid"]

    st.divider()

    chart_col, detail_col = st.columns([3, 2], gap="large")

    # ---------------------------------------------------------- Domain ladders
    with chart_col:
        st.subheader("Service levels by domain")
        st.caption(
            "&nbsp;&nbsp;".join(
                f"{LEVEL_SWATCH.get(l, '▪️')} {LEVEL_SHORT.get(l, l)}" for l in levels
            ),
            unsafe_allow_html=True,
        )
        for d in domains:
            counts = {level: sum(1 for s in filtered_sites if s["levels"][d["key"]] == level) for level in levels}
            pcts = {level: (counts[level] / total * 100 if total else 0) for level in levels}

            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=[LEVEL_SHORT[l] for l in levels],
                x=[pcts[l] for l in levels],
                orientation="h",
                marker=dict(color=[LEVEL_COLOR[l] for l in levels], cornerradius=4),
                text=[f"{counts[l]} ({pcts[l]:.1f}%)" for l in levels],
                textposition="inside",
                insidetextanchor="start",
                textfont=dict(size=12, color=[LEVEL_TEXT[l] for l in levels]),
                hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
            ))
            apply_chart_theme(
                fig,
                title=dict(text=d["question"], font=dict(size=14, color="#0f172a"), x=0.02),
                height=180,
                margin=dict(l=10, r=10, t=36, b=10),
                xaxis=dict(range=[0, 100], showgrid=True, gridcolor="#eef1f5", zeroline=False, ticksuffix="%"),
                yaxis=dict(automargin=True, showgrid=False),
                showlegend=False,
            )
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=f"jmp_domain_chart_{d['key']}")

        sanitation = next((d for d in domains if d["key"] == "sanitation"), None)
        if sanitation:
            st.caption(
                f"ℹ️ {sanitation['label']} excludes menstrual hygiene facilities (this form doesn't "
                "collect them) — see JMP_SCORING.md for the documented limitation."
            )

    # ------------------------------------------------------- Site detail panel
    with detail_col:
        site_by_uuid = {s["uuid"]: s for s in sites}
        ordered = sorted(sites, key=lambda s: s["name"])

        st.subheader("Facility detail")
        picked = st.selectbox(
            "Health center (or click a map marker above)",
            options=[s["uuid"] for s in ordered],
            format_func=lambda u: site_by_uuid[u]["name"],
            index=[s["uuid"] for s in ordered].index(st.session_state.jmp_selected_site)
            if st.session_state.jmp_selected_site in site_by_uuid else 0,
            key="jmp_site_select",
        )
        st.session_state.jmp_selected_site = picked
        selected = site_by_uuid[st.session_state.jmp_selected_site]

        overall_color = "#0ca30c" if selected["meets_jmp_basic_wash"] else "#94a3b8"
        overall_text = "Meets full JMP basic WASH" if selected["meets_jmp_basic_wash"] else "Does not meet all 5 domains"
        st.markdown(
            f"""
            <div style="display:flex; align-items:baseline; flex-wrap:wrap; gap:0.5rem; margin-top:0.2rem;">
              <span style="font-size:1.25rem; font-weight:600;">{selected['name']}</span>
            </div>
            <div style="color:{TEXT_GRAY}; font-size:0.9rem; margin-bottom:0.4rem;">
              {selected['atoll']} — {selected['island']}
            </div>
            <div style="margin-bottom:0.8rem;">
              <span class="level-badge" style="background:{rgba(overall_color, 0.15)}; color:{overall_color};">
                {overall_text}
              </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for d in domains:
            level = selected["levels"][d["key"]]
            color, text_color = LEVEL_COLOR[level], LEVEL_TEXT[level]
            st.markdown(
                f"""
                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid #eef1f5;">
                  <span style="font-size:0.88rem; color:{TEXT_GRAY};">{d['label']}</span>
                  <span class="level-badge" style="background:{color}; color:{text_color};">{LEVEL_SHORT[level]}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with st.expander("Raw JMP answers"):
            for q, val in selected["answers"].items():
                st.markdown(f"- **{q}**: {val}")
