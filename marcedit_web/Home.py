"""marcedit-web — landing page.

Stage 1 (bootstrap) placeholder: confirms the Docker stack boots and the
sidebar nav placeholder renders. Real upload + state wiring lands in
Stage 3 (session + identity).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="marcedit-web",
    page_icon="\N{BOOKS}",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("marcedit-web")
st.caption("MARC21 viewer, validator, editor, and diff — in your browser.")

st.info(
    "This is the Stage 1 bootstrap. The upload widget, validation, editor, "
    "and diff features are wired up in later stages. If you can read this, "
    "the Docker stack is healthy."
)

with st.sidebar:
    st.header("marcedit-web")
    st.caption("v0.1.0 (bootstrap)")
    st.divider()
    st.caption("Pages will appear above once added.")
