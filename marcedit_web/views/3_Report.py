"""Report — thin shim around :func:`marcedit_web.render.report.render`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import report, sidebar_status

session.init_page()

st.title("Report")
st.caption("Aggregate counts across the loaded batch plus a per-record table.")

sidebar_status()

report.render()
