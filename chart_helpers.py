"""Shared theming + map-building helpers used by both dashboard tabs.

Both tabs import from here instead of redefining the same font/color/theme
plumbing — see performance_tab.py and jmp_wash_tab.py.
"""
import folium
from folium.plugins import Fullscreen, MiniMap
from jinja2 import Template

FONT_FAMILY = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
TEXT_GRAY = "#475569"

ESRI_IMAGERY_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


def rgba(hex_color, alpha):
    """'#22a06b', 0.12 -> 'rgba(34,160,107,0.12)'. Plotly's color validator
    rejects 8-digit hex-with-alpha, so this is the portable way to get a
    tinted background from one of our brand hex colors."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def apply_chart_theme(fig, **layout_overrides):
    """Shared look for every Plotly chart: transparent background, quiet
    axes, consistent font — so charts read as part of the page, not boxed
    widgets."""
    fig.update_layout(
        font=dict(family=FONT_FAMILY, size=13, color=TEXT_GRAY),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="white", bordercolor="#e2e8f0", font=dict(family=FONT_FAMILY, size=13)),
        **layout_overrides,
    )
    return fig


def inject_page_css():
    """Inter font import + base typography. Call once from app.py — not
    from each tab — since it's identical for both and st.tabs executes
    every tab body on every rerun."""
    import streamlit as st
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        html, body, [class*="css"] {{ font-family: {FONT_FAMILY}; }}
        .block-container {{ padding-top: 2.2rem; }}
        h1, h2, h3 {{ font-family: {FONT_FAMILY}; letter-spacing: -0.01em; }}
        .level-badge {{
            display: inline-block; padding: 3px 12px; border-radius: 999px;
            font-size: 0.82rem; font-weight: 600;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_folium_map(sites, marker_color_fn, tooltip_fn, popup_fn, pad=0.6, get_gps=lambda s: s["gps"]):
    """A Folium map configured the same way for both tabs: Esri satellite +
    OpenStreetMap layers (togglable via LayerControl), a hospital-pin marker
    per site colored/labeled by the caller's own logic, zoom, fullscreen,
    and a minimap — fit to the sites' combined bounding box.

    sites: list of dicts, each with GPS reachable via get_gps(site) ->
        {"lat":..., "lon":...}. Skip sites with no GPS before calling this.
    marker_color_fn(site) -> a folium.Icon `color` name (fixed named
        palette — 'red'/'blue'/'darkgreen'/'orange'/'gray', etc., not hex).
    tooltip_fn(site) -> short string shown on hover.
    popup_fn(site) -> HTML string shown in the popup on click.
    """
    lats = [get_gps(s)["lat"] for s in sites]
    lons = [get_gps(s)["lon"] for s in sites]
    south, north = min(lats) - pad, max(lats) + pad
    west, east = min(lons) - pad, max(lons) + pad
    center = [(south + north) / 2, (west + east) / 2]

    m = folium.Map(location=center, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=ESRI_IMAGERY_TILES, attr="Esri", name="Satellite", overlay=False, control=True,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="Street", overlay=False, control=True).add_to(m)

    for s in sites:
        gps = get_gps(s)
        folium.Marker(
            location=[gps["lat"], gps["lon"]],
            tooltip=tooltip_fn(s),
            popup=folium.Popup(popup_fn(s), max_width=260),
            icon=folium.Icon(color=marker_color_fn(s), icon="hospital-o", prefix="fa"),
        ).add_to(m)

    m.fit_bounds([[south, west], [north, east]])
    Fullscreen(position="topleft").add_to(m)
    MiniMap(toggle_display=True, position="bottomleft").add_to(m)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)
    return m


class _LegendControl(folium.MacroElement):
    """A real Leaflet control (L.control(...).addTo(map)), not a raw HTML
    overlay — streamlit-folium's frontend only reliably renders content
    added the same way its own plugins (LayerControl/Fullscreen/MiniMap) add
    themselves. A plain `position: fixed` <div> injected via
    `map.get_root().html.add_child(...)` reaches the component's props fine
    (verified directly) but never appears on screen — presumably clipped or
    repositioned by a containing block inside the component's own wrapper.
    Going through L.control() sidesteps that entirely, since it's the exact
    mechanism the already-working controls use.
    """

    _template = Template(
        """
        {% macro script(this, kwargs) %}
        var {{ this.get_name() }} = L.control({position: {{ this.position|tojson }}});
        {{ this.get_name() }}.onAdd = function(map) {
            var div = L.DomUtil.create('div', 'leaflet-legend');
            div.innerHTML = {{ this.html|tojson }};
            return div;
        };
        {{ this.get_name() }}.addTo({{ this._parent.get_name() }});
        {% endmacro %}
        """
    )

    def __init__(self, html, position="bottomright"):
        super().__init__()
        self._name = "LegendControl"
        self.html = html
        self.position = position


def add_map_legend(m, title, items, position="bottomright"):
    """A small color-key box in a map corner — one colored row per
    (hex_color, label) in `items`. Bottom-right by default so it doesn't
    collide with the LayerControl box build_folium_map already puts at
    top-right.
    """
    rows = "".join(
        f'<div style="display:flex; align-items:center; gap:9px; padding:4px 10px;'
        f'border-radius:4px; margin-bottom:2px; background:{color}22;">'
        f'<span style="width:11px; height:11px; border-radius:50%; background:{color};'
        f'flex-shrink:0; border:1px solid rgba(0,0,0,0.15);"></span>'
        f'<span style="font-size:12.5px; color:#0f172a; font-weight:500;">{label}</span></div>'
        for color, label in items
    )
    html = (
        f'<div style="background:white; padding:10px 10px 6px 10px; border-radius:8px; '
        f'box-shadow:0 1px 6px rgba(0,0,0,0.3); min-width:150px; '
        f'font-family: Inter, -apple-system, sans-serif;">'
        f'<div style="font-size:12px; font-weight:600; color:#0f172a; margin-bottom:6px;">{title}</div>'
        f"{rows}</div>"
    )
    _LegendControl(html, position=position).add_to(m)
