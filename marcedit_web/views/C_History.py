"""History — thin shim around :func:`marcedit_web.render.history.render`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import history, sidebar_status

session.init_page()

st.title("History")
st.caption(
    "Every change made to your loaded file — task runs, quick "
    "operations, and edits — plus the export of the current version."
)

sidebar_status()

history.render()
