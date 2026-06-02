"""MarcEditor — thin shim around :mod:`marcedit_web.render.edit`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import edit, rules_for_page, sidebar_status

session.init_page()

st.title("MarcEditor")
st.caption(
    "Edit the loaded batch as MarcEdit-style `.mrk` text. Apply runs the "
    "parser and validators; Save serializes back to `.mrc` and updates this "
    "session's records so View / Validate / Report / Diff see the edits."
)

sidebar_status()

edit.render(rules_for_page())
