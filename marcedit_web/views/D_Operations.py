"""Operations — private durable-queue console."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import operations, sidebar_status


session.init_page()

st.title("Operations")
st.caption(
    "Track saved-task runs, review retained results, and act on work that "
    "needs attention."
)

sidebar_status()

operations.render()
