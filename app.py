#!/usr/bin/env python3
"""MOHHS RMI health-center dashboards — entry point.

Three dashboards, one app, three tabs (no sidebar page-switcher):
  - Performance Assessment (performance_tab.py): score trends and
    improvement-plan tracking for the 18 Register=Y health centers.
  - Essential Meds & Supplies (meds_tab.py): stock availability against the
    112-item essential meds/supplies checklist, live from the MIS.
  - JMP WASH Facility Assessment (jmp_wash_tab.py): JMP-2018 WASH
    service-level ladders for the 19 submitted facility assessments.

Each tab owns its own data loading — this script itself makes no API calls
or data processing.
See README.md for setup/running and VISUALS.md for what each chart shows
and where its data comes from.
"""
import streamlit as st

from chart_helpers import inject_page_css
from jmp_wash_tab import render_jmp_wash_tab
from meds_tab import render_meds_tab
from performance_tab import render_performance_tab

st.set_page_config(page_title="MOHHS RMI Health Center Dashboards", layout="wide")
inject_page_css()

tab1, tab2, tab3 = st.tabs(
    ["Performance Assessment", "Essential Meds & Supplies", "JMP WASH Facility Assessment"]
)

with tab1:
    render_performance_tab()

with tab2:
    render_meds_tab()

with tab3:
    render_jmp_wash_tab()
