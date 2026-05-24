"""View — `.mrk` record viewer with click-through help.

Thin shim around :func:`marcedit_web.render.view.render`. The new
Workspace page (`pages/0_Workspace.py`) composes the same render
function inside a tab; this file is the dedicated deep-link path.
"""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import rules_for_page, sidebar_status, view

st.set_page_config(page_title="View · marcedit-web", layout="wide")
session.init()

st.title("View")
st.caption("MarcEdit-style `.mrk` rendering of the loaded batch.")

sidebar_status()

view.render(rules_for_page())
