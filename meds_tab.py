"""Essential Meds & Supplies tab — stock availability from the
"NI HC - Essential Meds and Supplies Checklist" form (1783385736711).

Reads meds_data.json — a committed snapshot of the MIS written by
build_live_data.py. This tab makes no API calls at runtime: the deployed
instance needs no MIS credentials, loads instantly, and keeps working when
the MIS is down. Re-run build_live_data.py and commit to refresh.

The two scored sections (Essential Supplies, Essential Meds) are shown
side by side rather than combined into one number: a health center can be
well stocked on equipment and out of medicines, and averaging the two would
hide exactly that. See VISUALS.md for what each element shows.
"""
import json
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from chart_helpers import FONT_FAMILY, TEXT_GRAY, add_map_legend, apply_chart_theme, atoll_multiselect, build_folium_map, rgba

HERE = Path(__file__).resolve().parent
# The canonical 18-site registry (display name, atoll, GPS) that
# build_performance_data.py already resolved from the MIS registration form
# plus geojson centroid fallbacks — reused here rather than re-deriving it, so
# a health center is named and placed identically on every tab.
SITES_PATH = HERE / "performance_data.json"
DATA_PATH = HERE / "meds_data.json"

# Stock-availability bands. These are a *dashboard display convention*, not an
# MOHHS target: this form carries no "meets target" field of its own (unlike
# the Performance Assessment, which defines >85%), so there is no official
# threshold to honour here. They exist to make the charts readable at a glance.
BAND_GOOD, BAND_PARTIAL, BAND_LOW = "#22a06b", "#f2a93b", "#e5484d"
GOOD_FROM, PARTIAL_FROM = 80, 50

SECTION_COLOR = {"meds": "#7c3aed", "supplies": "#0e7490"}
TRACK = "#eef1f5"
MAP_GOOD, MAP_PARTIAL, MAP_LOW = "darkgreen", "orange", "red"
MAP_HEIGHT = 520
MAP_HEX = {MAP_GOOD: "#728224", MAP_PARTIAL: "#F69730", MAP_LOW: "#D63E2A"}

def band_color(pct):
    if pct is None:
        return "#94a3b8"
    return BAND_GOOD if pct >= GOOD_FROM else BAND_PARTIAL if pct >= PARTIAL_FROM else BAND_LOW


def band_map_color(pct):
    if pct is None:
        return "gray"
    return MAP_GOOD if pct >= GOOD_FROM else MAP_PARTIAL if pct >= PARTIAL_FROM else MAP_LOW


def round_label(r):
    import calendar
    year, month = r.split("-")
    return f"{calendar.month_name[int(month)]} {year}"


@st.cache_data
def load_site_registry():
    return json.loads(SITES_PATH.read_text())["sites"]


@st.cache_data
def load_meds_data():
    """The committed MIS snapshot (build_live_data.py), or None if it hasn't
    been built yet."""
    if not DATA_PATH.exists():
        return None
    return json.loads(DATA_PATH.read_text())


def section_by_key(schema, key):
    return next(s for s in schema["sections"] if s["key"] == key)


def missing_items(schema, record, section_key):
    """[(category_label, [missing item labels])] for one site's section, in
    form order, skipping categories that are fully stocked."""
    out = []
    for cat in section_by_key(schema, section_key)["categories"]:
        have = set(record["sections"][section_key]["categories"][cat["key"]]["have"])
        gaps = [i["label"] for i in cat["items"] if i["value"] not in have]
        if gaps:
            out.append((cat["label"], gaps))
    return out


def render_category_breakdown(schema, record, section_key, chart_key):
    """One row per checklist category: items in stock (colored by the bands
    above) on a track the full width of that category's item count."""
    section = section_by_key(schema, section_key)
    cats = section["categories"]
    order = list(reversed(cats))  # Plotly draws the first category at the bottom
    have = [len(record["sections"][section_key]["categories"][c["key"]]["have"]) for c in order]
    maxes = [c["max_points"] for c in order]
    colors = [band_color(100 * h / m if m else 0) for h, m in zip(have, maxes)]
    names = [c["label"] for c in order]
    widest = max(maxes)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=names, x=have, orientation="h", marker=dict(color=colors, cornerradius=3),
        customdata=maxes, hovertemplate="<b>%{y}</b><br>In stock: %{x} of %{customdata}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=names, x=[m - h for h, m in zip(have, maxes)], orientation="h",
        marker=dict(color=TRACK, cornerradius=3), customdata=maxes,
        hovertemplate="<b>%{y}</b><br>Missing: %{x} of %{customdata}<extra></extra>",
    ))
    apply_chart_theme(
        fig,
        barmode="stack", bargap=0.34, showlegend=False, dragmode=False,
        height=36 + 27 * len(order),
        margin=dict(l=10, r=10, t=6, b=6),
        xaxis=dict(range=[0, widest * 1.32], fixedrange=True, showgrid=False, zeroline=False, visible=False),
        yaxis=dict(automargin=True, fixedrange=True, showgrid=False, ticksuffix="  ", tickfont=dict(size=11.5)),
        annotations=[
            dict(x=widest * 1.04, y=n, xref="x", yref="y", text=f"{h}/{m}", showarrow=False,
                 xanchor="left", font=dict(size=11, color=c, family=FONT_FAMILY))
            for n, h, m, c in zip(names, have, maxes, colors)
        ],
    )
    st.plotly_chart(fig, key=chart_key, width="stretch", config={"displayModeBar": False, "scrollZoom": False})


def render_meds_tab():
    st.title("Essential Meds & Supplies")

    data = load_meds_data()
    if data is None:
        st.error(
            f"No checklist snapshot found ({DATA_PATH.name}). "
            "Run `python3 build_live_data.py` and commit the result.",
            icon="🚫",
        )
        st.stop()

    schema, meta = data["schema"], data["meta"]
    if not data["rounds"]:
        st.info("No checklist submissions with a monitoring round have been recorded yet.", icon="📋")
        st.stop()

    round_keys = sorted(data["rounds"])
    st.caption(
        f"{sum(s['max_points'] for s in schema['sections'])} checklist items · "
        f"{len(schema['sections'])} sections · {len(round_keys)} round(s) · "
        f"{meta['n_submissions']} submissions on the form"
    )

    round_key = (
        st.selectbox("Round", options=round_keys, format_func=round_label,
                     index=len(round_keys) - 1, key="meds_round")
        if len(round_keys) > 1 else round_keys[0]
    )
    round_data = data["rounds"][round_key]
    coverage = meta["rounds"][round_key]

    registry = {s["site_key"]: s for s in load_site_registry()}
    sites = [
        {**registry[k], "record": rec, "meds_pct": rec["sections"]["meds"]["pct"],
         "supplies_pct": rec["sections"]["supplies"]["pct"]}
        for k, rec in round_data.items() if k in registry
    ]
    sites.sort(key=lambda s: s["display_name"])
    if not sites:
        st.info(f"No registered health center has reported for {round_label(round_key)} yet.", icon="📋")
        st.stop()

    # The selectbox's own widget key IS the selection state. A keyed widget
    # restores its stored value on every rerun and ignores `index`, so a
    # separate state variable gets overwritten by the stale widget value the
    # moment the selectbox is drawn -- which is exactly why clicking a bar
    # used to do nothing. Map and chart clicks below write to this key
    # directly; both run before the selectbox is instantiated, which is what
    # makes assigning to it legal.
    site_keys = {s["site_key"] for s in sites}
    if st.session_state.get("meds_site_select") not in site_keys:
        st.session_state.meds_site_select = min(sites, key=lambda s: s["meds_pct"])["site_key"]

    # --------------------------------------------------------- Atoll filter
    all_atolls = sorted({s["atoll"] for s in sites})
    selected_atolls = atoll_multiselect(
        "Filter by atoll/island", all_atolls, key="meds_atoll_filter",
        help="Scopes the KPIs, map and charts below.",
    )
    filtered = [s for s in sites if s["atoll"] in selected_atolls]
    if not filtered:
        st.warning("No health centers match the selected filter.")
        st.stop()

    # ------------------------------------------------------------- KPI row
    n = len(filtered)
    meds_avg = round(sum(s["meds_pct"] for s in filtered) / n)
    sup_avg = round(sum(s["supplies_pct"] for s in filtered) / n)
    fully = sum(1 for s in filtered if s["meds_pct"] >= GOOD_FROM and s["supplies_pct"] >= GOOD_FROM)
    kpis = st.columns(4)
    meds_label = section_by_key(schema, "meds")["label"]
    supplies_label = section_by_key(schema, "supplies")["label"]
    kpis[0].metric("Health centers reporting", n)
    kpis[1].metric(f"Avg. {meds_label.lower()} in stock", f"{meds_avg}%")
    kpis[2].metric(f"Avg. {supplies_label.lower()} in stock", f"{sup_avg}%")
    kpis[3].metric(f"Both sections ≥{GOOD_FROM}%", f"{fully} of {n}")
    st.caption(
        f"🟩 ≥{GOOD_FROM}% in stock &nbsp;&nbsp; 🟨 {PARTIAL_FROM}–{GOOD_FROM - 1}% &nbsp;&nbsp; 🟥 &lt;{PARTIAL_FROM}% "
        "&nbsp;&nbsp;|&nbsp;&nbsp; a dashboard reading aid, not an MOHHS target — this form sets none.",
        unsafe_allow_html=True,
    )

    st.divider()

    # ----------------------------------------------------------------- Map
    st.subheader("Map")
    st.caption(f"🏥 colored by {meds_label.lower()} availability. "
               "Hover for both scores, click to load the checklist below.")
    gps_sites = [s for s in filtered if s["gps"]]

    def popup(s):
        return (f"<b>{s['display_name']}</b><br>{meds_label}: {s['meds_pct']}%"
                f"<br>{supplies_label}: {s['supplies_pct']}%")

    m, view = build_folium_map(
        gps_sites,
        lambda s: band_map_color(s["meds_pct"]),
        lambda s: f"{s['display_name']} — meds {s['meds_pct']}%, supplies {s['supplies_pct']}%",
        popup,
        height_px=MAP_HEIGHT,
    )
    counts = {c: sum(1 for s in gps_sites if band_map_color(s["meds_pct"]) == c) for c in (MAP_GOOD, MAP_PARTIAL, MAP_LOW)}
    total_gps = len(gps_sites) or 1
    add_map_legend(m, f"{meds_label} in stock", [
        (MAP_HEX[MAP_GOOD], f"≥{GOOD_FROM}% ({round(100 * counts[MAP_GOOD] / total_gps)}%)"),
        (MAP_HEX[MAP_PARTIAL], f"{PARTIAL_FROM}–{GOOD_FROM - 1}% ({round(100 * counts[MAP_PARTIAL] / total_gps)}%)"),
        (MAP_HEX[MAP_LOW], f"<{PARTIAL_FROM}% ({round(100 * counts[MAP_LOW] / total_gps)}%)"),
    ])
    map_state = st_folium(
        m, use_container_width=True, height=MAP_HEIGHT, key="meds_folium_map",
        center=view["center"], zoom=view["zoom"],  # required for the fit to stick -- see fit_zoom
        returned_objects=["last_object_clicked"],
    )
    clicked = (map_state or {}).get("last_object_clicked")
    if clicked and gps_sites:
        best = min(gps_sites, key=lambda s: (s["gps"]["lat"] - clicked["lat"]) ** 2 + (s["gps"]["lon"] - clicked["lng"]) ** 2)
        st.session_state.meds_site_select = best["site_key"]

    st.divider()

    chart_col, detail_col = st.columns([3, 2], gap="large")

    # -------------------------------------------------- Ranked availability
    with chart_col:
        st.subheader("Stock availability by health center")
        st.caption(" · ".join(s["label"] for s in schema["sections"]))
        st.caption("👆 Click any bar to load that health center's checklist on the right.")

        order = sorted(filtered, key=lambda s: s["meds_pct"])  # highest ends up on top
        names = [s["display_name"] for s in order]
        no_dim = dict(selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)))

        fig = go.Figure()
        for key, label in ((s["key"], s["label"]) for s in reversed(schema["sections"])):
            fig.add_trace(go.Bar(
                name=label, y=names, x=[s[f"{key}_pct"] for s in order], orientation="h",
                customdata=[[s["site_key"], s["record"]["sections"][key]["score"],
                             s["record"]["sections"][key]["max"]] for s in order],
                marker=dict(color=SECTION_COLOR[key], cornerradius=4),
                hovertemplate=("<b>%{y}</b> — " + label +
                               "<br>%{customdata[1]} of %{customdata[2]} items in stock (%{x}%)<extra></extra>"),
                **no_dim,
            ))

        shapes = []
        keys_in_order = [s["site_key"] for s in order]
        if st.session_state.meds_site_select in keys_in_order:
            idx = keys_in_order.index(st.session_state.meds_site_select)
            shapes.append(dict(type="rect", xref="paper", x0=0, x1=1, yref="y",
                               y0=idx - 0.5, y1=idx + 0.5,
                               fillcolor="rgba(124,58,237,0.07)", line=dict(width=0), layer="below"))

        apply_chart_theme(
            fig, barmode="group", bargap=0.3, bargroupgap=0.12,
            height=90 + 46 * len(order),
            # b leaves room for the x-axis title below the tick labels;
            # at the default 10 the two overlap.
            margin=dict(l=10, r=10, t=10, b=48), dragmode=False,
            xaxis=dict(title="Items in stock (%)", range=[0, 105], fixedrange=True,
                       showgrid=True, gridcolor="#eef1f5", zeroline=False, ticksuffix="%"),
            yaxis=dict(automargin=True, fixedrange=True, showgrid=False, ticksuffix="  "),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
            shapes=shapes,
        )
        event = st.plotly_chart(fig, on_select="rerun", key="meds_rank_chart", width="stretch",
                                config={"displayModeBar": False, "scrollZoom": False})
        if event and event.selection and event.selection.get("points"):
            clicked_bar = event.selection["points"][0].get("customdata")
            if clicked_bar and clicked_bar[0] != st.session_state.meds_site_select:
                st.session_state.meds_site_select = clicked_bar[0]
                st.rerun()  # redraw the detail panel, which this run already passed

        # ------------------------------------------- Most commonly missing
        st.subheader("Most commonly out of stock")
        st.caption(f"Items missing at the most health centers, across the {len(filtered)} reporting here.")
        gaps = []
        for section in schema["sections"]:
            for cat in section["categories"]:
                for item in cat["items"]:
                    n_missing = sum(
                        1 for s in filtered
                        if item["value"] not in s["record"]["sections"][section["key"]]["categories"][cat["key"]]["have"]
                    )
                    if n_missing:
                        gaps.append((n_missing, item["label"], section["key"]))
        section_labels = {s["key"]: s["label"] for s in schema["sections"]}
        gaps.sort(key=lambda g: (-g[0], g[1]))
        top = list(reversed(gaps[:12]))

        if not top:
            st.success("Every checklist item is in stock at every health center shown.", icon="✅")
        else:
            fig2 = go.Figure(go.Bar(
                y=[f"{label[:46]}{'…' if len(label) > 46 else ''}" for _, label, _ in top],
                x=[c for c, _, _ in top], orientation="h",
                marker=dict(color=[SECTION_COLOR[s] for _, _, s in top], cornerradius=4),
                customdata=[[label, section_labels[s]] for _, label, s in top],
                text=[str(c) for c, _, _ in top], textposition="outside",
                textfont=dict(size=12, color=TEXT_GRAY), cliponaxis=False,
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Missing at %{x} health center(s)<extra></extra>",
            ))
            apply_chart_theme(
                fig2, height=110 + 30 * len(top), margin=dict(l=10, r=10, t=10, b=48),
                showlegend=False, dragmode=False, bargap=0.35,
                xaxis=dict(title="Health centers missing it", range=[0, len(filtered) * 1.15],
                           fixedrange=True, showgrid=True, gridcolor="#eef1f5", zeroline=False, dtick=1),
                yaxis=dict(automargin=True, fixedrange=True, showgrid=False, ticksuffix="  ",
                           tickfont=dict(size=11.5)),
            )
            st.plotly_chart(fig2, key="meds_gap_chart", width="stretch", config={"displayModeBar": False})

    # -------------------------------------------------------- Detail panel
    with detail_col:
        by_key = {s["site_key"]: s for s in sites}
        ordered_keys = [s["site_key"] for s in sorted(sites, key=lambda s: -s["meds_pct"])]

        st.subheader("Checklist detail")
        picked = st.selectbox(
            "Health center (or click a bar on the left)",
            options=ordered_keys,
            format_func=lambda k: f"{by_key[k]['display_name']} — meds {by_key[k]['meds_pct']}%",
            key="meds_site_select",  # no `index`: the key above is the state
        )
        selected = by_key[picked]
        record = selected["record"]

        st.markdown(
            f"<div style='font-size:1.25rem; font-weight:600; margin-top:0.2rem;'>{selected['display_name']}</div>"
            f"<div style='color:{TEXT_GRAY}; font-size:0.9rem; margin-bottom:0.6rem;'>"
            f"{selected['atoll']} · submitted {record['created']}</div>",
            unsafe_allow_html=True,
        )

        badges = []
        for section in schema["sections"]:
            sec = record["sections"][section["key"]]
            color = band_color(sec["pct"])
            badges.append(
                f"<div style='flex:1; min-width:130px; background:{rgba(color, 0.1)}; "
                f"border:1px solid {rgba(color, 0.3)}; border-radius:10px; padding:8px 12px;'>"
                f"<div style='font-size:0.78rem; color:{TEXT_GRAY};'>{section['label']}</div>"
                f"<div style='font-size:1.35rem; font-weight:700; color:{color};'>{sec['pct']}%</div>"
                f"<div style='font-size:0.78rem; color:{TEXT_GRAY};'>{sec['score']} of {sec['max']} in stock</div>"
                f"</div>"
            )
        st.markdown(f"<div style='display:flex; gap:10px; margin-bottom:0.9rem;'>{''.join(badges)}</div>",
                    unsafe_allow_html=True)

        if record.get("round_inferred"):
            st.caption(
                f"ℹ️ No monitoring round was selected on this submission — it is filed under "
                f"{round_label(round_key)} from its own form date ({record.get('date', 'n/a')})."
            )
        if any(record["sections"][s["key"]]["score_derived"] for s in schema["sections"]):
            st.caption("ℹ️ This submission predates the form's score fields — its score is recounted from the ticked items.")

        section_tabs = st.tabs([s["label"] for s in schema["sections"]])
        for tab, section in zip(section_tabs, schema["sections"]):
            with tab:
                render_category_breakdown(schema, record, section["key"], f"meds_breakdown_{section['key']}")
                gaps = missing_items(schema, record, section["key"])
                n_missing = sum(len(g) for _, g in gaps)
                if not n_missing:
                    st.success(f"All {section['max_points']} items in stock.", icon="✅")
                else:
                    with st.expander(f"Out of stock — {n_missing} item(s)"):
                        for cat_label, items in gaps:
                            st.markdown(f"_{cat_label}_")
                            for item in items:
                                st.markdown(f"- {item}")
