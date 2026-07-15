#!/usr/bin/env python3
"""MOHHS RMI health-center dashboards — entry point.

Two dashboards, one app, two tabs (no sidebar page-switcher):
  - Performance Assessment (performance_tab.py): score trends and
    improvement-plan tracking for the 18 Register=Y health centers.
  - JMP WASH Facility Assessment (jmp_wash_tab.py): JMP-2018 WASH
    service-level ladders for the 19 submitted facility assessments.

Both tabs read their own pre-built JSON (performance_data.json /
jmp_data.json) — this script itself makes no API calls or data processing.
See README.md for setup/running and VISUALS.md for what each chart shows
and where its data comes from.
"""
import streamlit as st

from chart_helpers import inject_page_css
from jmp_wash_tab import render_jmp_wash_tab
from performance_tab import render_performance_tab

st.set_page_config(page_title="MOHHS RMI Health Center Dashboards", layout="wide")
inject_page_css()

tab1, tab2 = st.tabs(["Performance Assessment", "JMP WASH Facility Assessment"])

with tab1:
    render_performance_tab()

with tab2:
    render_jmp_wash_tab()
