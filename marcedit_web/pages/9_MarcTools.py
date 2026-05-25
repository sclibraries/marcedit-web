"""Marc Tools — thin shim around :func:`marcedit_web.render.marc_tools.render`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import marc_tools, sidebar_status

st.set_page_config(page_title="Marc Tools · marcedit-web", layout="wide")
session.init_page()

sidebar_status()

marc_tools.render()
