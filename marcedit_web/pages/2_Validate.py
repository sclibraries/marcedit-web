"""Validate — thin shim around :func:`marcedit_web.render.validate.render`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import rules_and_warnings_for_page, sidebar_status, validate

st.set_page_config(page_title="Validate · marcedit-web", layout="wide")
session.init_page()

st.title("Validate")
st.caption("Structural preflight + rules from `data/marc-rules.txt`.")

sidebar_status()

rule_set, warnings = rules_and_warnings_for_page()
validate.render(rule_set, warnings)
