"""MapLibre GL maps + the quantile colour scale, as a Streamlit component.

This is MapLibre GL JS directly (map_component/index.html), not pydeck. The
reason is the two things pydeck cannot do:

  - **Controls inside the map.** pydeck renders a picture; there is nowhere to
    put a layer switcher or a legend, so both had to sit in the page above and
    beside it. MapLibre takes real corner-anchored controls, so the measure
    picker, the basemap picker and the legend live in the map.
  - **Raster basemaps.** pydeck's declarative JSON cannot supply TileLayer's
    `renderSubLayers` callback, so raster tiles fail as GeoJsonLayer. That
    mattered here because RMI's atolls are thin reef rings which vector styles
    draw sub-pixel at the zoom that fits the country -- land and sea washed
    into one flat colour. It forced a workaround: drawing the country's admin
    polygons as a vector layer underneath. MapLibre has native raster sources,
    so the basemap simply shows the atolls and the workaround is gone.

Switching measure or basemap is handled entirely in the browser -- no Streamlit
rerun -- so the map responds instantly. Only a marker *click* comes back to
Python, since that drives the detail panel outside the map.

Colour: markers are binned by QUANTILE of the selected measure, so the bins
always split the sites actually on screen rather than against fixed thresholds
that might put everything in one bucket. Quantiles rank sites against each
other, not against a target; the legend says so and prints each bin's real
value range and count.
"""
import math
import pathlib

import streamlit.components.v1 as components

_COMPONENT = components.declare_component(
    "mohhs_maplibre_map", path=str(pathlib.Path(__file__).resolve().parent / "map_component"),
)

# Single-hue ordinal ramp, light -> dark. Orange rather than the default
# sequential blue: every basemap here is ocean, and blue markers on blue water
# have no figure/ground separation. These steps were validated rather than
# eyeballed -- monotone lightness, adjacent dL >= 0.06, light end 2.42:1 on a
# light surface, hue spread 4 degrees. A sequential measure gets one hue,
# never a rainbow.
QUANTILE_RAMP = ["#ef8a5c", "#e0661f", "#b0430e", "#722a09"]
NO_DATA_COLOR = "#b9b9b3"

LEGEND_NOTE = "Quantiles rank these health centers against each other, not against a target."

# Esri raster tiles: token-free, one provider, one attribution. Esri orders the
# path {z}/{y}/{x}, not {z}/{x}/{y}.
#
# Ocean is the default because it renders bathymetry and reef outlines, so the
# atoll chains read as places rather than as dots on a wash. The other free
# raster sources were checked and rejected: OpenStreetMap's volunteer servers
# answer HTTP 418 "Access blocked" for a deployed app, and CARTO's raster
# endpoint now returns an "API KEY REQUIRED" tile.
#
# No dark basemap on purpose: the ramp above is validated against a LIGHT
# surface, and a dark surface needs its own validated steps, not a reused one.
def _esri(service, attribution="Tiles &copy; Esri"):
    return {
        "tiles": f"https://server.arcgisonline.com/ArcGIS/rest/services/{service}/MapServer/tile/{{z}}/{{y}}/{{x}}",
        "attribution": attribution,
    }


BASEMAPS = {
    "Ocean": _esri("Ocean/World_Ocean_Base"),
    "Street": _esri("World_Street_Map"),
    "Satellite": _esri("World_Imagery"),
}
DEFAULT_BASEMAP = "Ocean"

MAX_FIT_ZOOM = 13
BOUNDS_PAD_FRACTION = 0.06
BOUNDS_PAD_MIN_DEGREES = 0.04
TILE_SIZE = 256


def _mercator_y(lat):
    lat = max(min(lat, 85.05), -85.05)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def bounds_for(values):
    """(low, high) for one axis, padded proportionally to its own span so a
    single-site view isn't left adrift in open ocean."""
    low, high = min(values), max(values)
    pad = max((high - low) * BOUNDS_PAD_FRACTION, BOUNDS_PAD_MIN_DEGREES)
    return low - pad, high + pad


def fit_zoom(south, west, north, east, width_px, height_px):
    """Largest integer zoom at which the box fits the viewport. Used for the
    map's opening view; the component also calls fitBounds once the container
    has its real size, which is the part that has to be right."""
    lon_span = max(east - west, 1e-6)
    lat_span = max(_mercator_y(north) - _mercator_y(south), 1e-6)
    zoom_lon = math.log2(width_px * 360 / (TILE_SIZE * lon_span))
    zoom_lat = math.log2(height_px * 2 * math.pi / (TILE_SIZE * lat_span))
    return max(0, min(MAX_FIT_ZOOM, math.floor(min(zoom_lon, zoom_lat))))


def quantile_bins(values, n_bins=len(QUANTILE_RAMP)):
    """Cut points splitting `values` into `n_bins` equal-count groups.

    Ties are not split: identical values always land in the same bin, so a
    heavy tie yields fewer bins than asked for (a 1-point question group is
    0% or 100%, hence two). That is honest, and the legend shows it by
    printing each bin's real range and count.
    """
    ordered = sorted(v for v in values if v is not None)
    if len(ordered) < 2:
        return []
    cuts = [ordered[min(int(i * len(ordered) / n_bins), len(ordered) - 1)] for i in range(1, n_bins)]
    return sorted(set(cuts))


def bin_index(value, cuts):
    """Which bin `value` falls in: 0 .. len(cuts)."""
    if value is None:
        return None
    return sum(1 for c in cuts if value >= c)


def color_for_bin(i, n_bins):
    """Ramp colour for bin `i` of `n_bins`, spread across the full ramp so a
    3-bin scale still runs light -> dark instead of using only its first three
    steps. Mirrors colorOf() in the component."""
    if i is None:
        return NO_DATA_COLOR
    return QUANTILE_RAMP[round(i * (len(QUANTILE_RAMP) - 1) / max(n_bins - 1, 1))]


def quantile_legend(values, cuts, label_fmt="{:.0f}%"):
    """[{color, label, count}] per bin, lowest first."""
    present = [v for v in values if v is not None]
    n_bins = len(cuts) + 1
    rows = []
    for i in range(n_bins):
        members = [v for v in present if bin_index(v, cuts) == i]
        if members:
            lo, hi = min(members), max(members)
            label = label_fmt.format(lo) if lo == hi else f"{label_fmt.format(lo)}–{label_fmt.format(hi)}"
        else:
            label = "—"
        rows.append({"color": color_for_bin(i, n_bins), "label": label, "count": len(members)})
    return rows


def build_metric(key, label, values, value_format="{}%"):
    """One entry for the in-map measure picker: its quantile cuts, its legend
    and the per-site values the browser recolours from."""
    cuts = quantile_bins([v for v in values if v is not None])
    return {
        "key": key,
        "label": label,
        "values": [None if v is None else round(v, 1) for v in values],
        "cuts": cuts,
        "legend": quantile_legend(values, cuts),
        "format": value_format.replace("{}", "{}"),
    }


def categorical_metric(key, label, values, color_of, label_of):
    """A metric whose colours are fixed per category rather than binned --
    the JMP service ladder, where "Basic" means Basic regardless of who else
    is on screen. Expressed in the same shape the picker expects: one bin per
    category, with cuts that put each value in its own bin."""
    categories = list(dict.fromkeys(label_of(v) for v in values if v is not None))
    index = {c: i for i, c in enumerate(categories)}
    return {
        "key": key,
        "label": label,
        "values": [None if v is None else index[label_of(v)] for v in values],
        "cuts": list(range(1, len(categories))),
        "colors": [color_of(c) for c in categories],
        "legend": [
            {"color": color_of(c), "label": c,
             "count": sum(1 for v in values if v is not None and label_of(v) == c)}
            for c in categories
        ],
        "format": "{}",
    }


def render_map(points, metrics, key, height=520, metric_title="Colour markers by",
               basemap=DEFAULT_BASEMAP, radius=8, legend_note=LEGEND_NOTE, get_gps=lambda p: p["gps"]):
    """Draw the map and return the site_key of a clicked marker, or None.

    points: [{site_key, gps:{lat,lon}, tooltip}] -- tooltip is HTML, and the
        selected measure's own value is appended to it by the component.
    metrics: from build_metric()/categorical_metric(), in picker order. Their
        `values` lists are positional against `points`.
    """
    south, north = bounds_for([get_gps(p)["lat"] for p in points])
    west, east = bounds_for([get_gps(p)["lon"] for p in points])
    spec = {
        "points": [
            {"site_key": p["site_key"], "lat": get_gps(p)["lat"], "lon": get_gps(p)["lon"],
             "tooltip": p["tooltip"]}
            for p in points
        ],
        "metrics": metrics,
        "metric": metrics[0]["key"],
        "metric_title": metric_title,
        "basemaps": BASEMAPS,
        "basemap": basemap,
        "ramp": QUANTILE_RAMP,
        "no_data_color": NO_DATA_COLOR,
        "legend_note": legend_note,
        "height": height,
        "radius": radius,
        "max_zoom": MAX_FIT_ZOOM,
        "view": {"lat": (south + north) / 2, "lon": (west + east) / 2,
                 "zoom": fit_zoom(south, west, north, east, 1100, height)},
        "bounds": [[west, south], [east, north]],
    }
    result = _COMPONENT(spec=spec, key=key, default=None)
    return (result or {}).get("site_key")
