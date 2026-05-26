"""Find — thin shim around :func:`marcedit_web.render.find.render`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import find, sidebar_status

st.set_page_config(page_title="Find · marcedit-web", layout="wide")
session.init_page()

st.title("Find")
sidebar_status()

find.render()
