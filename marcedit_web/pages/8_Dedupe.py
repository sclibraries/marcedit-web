"""Dedupe — thin shim around :func:`marcedit_web.render.dedupe.render`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import dedupe, sidebar_status

st.set_page_config(page_title="Dedupe · marcedit-web", layout="wide")
session.init_page()

st.title("Dedupe")
st.caption(
    "Find duplicates within the loaded batch, pick keepers, export deletes."
)

sidebar_status()

dedupe.render()
