"""Shared theming helpers used by all three dashboard tabs.

Each tab imports from here instead of redefining the same font/color/theme
plumbing. Maps live in map_helpers.py.
"""
FONT_FAMILY = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
TEXT_GRAY = "#475569"

ALL_ATOLLS_OPTION = "All"


def atoll_multiselect(label, all_atolls, key, help=None):
    """A 'Filter by atoll' multiselect that defaults to a single "All" pill
    instead of one pill per atoll -- with a dozen-plus atolls, defaulting to
    every one pre-selected renders as a wall of pills that looks cluttered.
    Selecting "All" (the default) means every atoll; picking specific
    atolls instead scopes down to just those. Returns the resolved list of
    atolls to filter by (never empty unless the user explicitly deselects
    everything, including "All")."""
    import streamlit as st

    selected = st.multiselect(
        label, options=[ALL_ATOLLS_OPTION] + all_atolls, default=[ALL_ATOLLS_OPTION], help=help, key=key,
    )
    if ALL_ATOLLS_OPTION in selected:
        return all_atolls
    return selected


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
