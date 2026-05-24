"""Diff tab — pointer to the dedicated Diff page.

The full multi-file Diff workflow is large (uploads, match-field config,
record-pair inspection, exports) and has its own independent session
state. Rather than duplicate it inside the Workspace tabs, we keep the
authoritative implementation at ``pages/6_Diff.py`` and surface a
launcher here.

Stage 15 will revisit this to add in-file dedupe directly inside the
Workspace.
"""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """Render the Diff tab into the current Streamlit container."""
    st.info(
        "Diff has its own workflow (independent uploads, match-field "
        "configuration, record-pair inspection, adds/deletes exports). "
        "Open the dedicated **Diff** page from the sidebar to use it."
    )
    st.markdown(
        "**Coming in v2.5 (Stage 15):** in-file duplicate detection "
        "directly in this tab — load one file, pick match fields, pick "
        "keepers, export the deletes."
    )
    st.link_button("Open Diff", url="/Diff", use_container_width=False)
