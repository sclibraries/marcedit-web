"""Shared helpers + per-tab render functions for the Workspace.

Every existing page slimmed down to a thin shim that calls one of the
``render.*`` modules. The new ``pages/0_Workspace.py`` composes the same
render functions inside ``st.tabs([...])`` so a cataloger doesn't have
to navigate the sidebar for every step of a single-batch workflow.

The render functions render the CONTENT only — no ``st.set_page_config``,
no sidebar, no page-level upload guard. Those stay with the page shim
(or the Workspace) so each function can be composed freely.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from marcedit_web.lib import rules as rules_mod
from marcedit_web.lib import session


_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "marc-rules.txt"


@st.cache_data(show_spinner=False)
def _load_rules(path_str: str, mtime: float):
    return rules_mod.parse_rules(Path(path_str))


def rules_for_page() -> rules_mod.RuleSet:
    """Parse the shipped marc-rules.txt once per server lifetime."""
    if not _RULES_PATH.exists():
        return rules_mod.RuleSet()
    rule_set, _ = _load_rules(str(_RULES_PATH), _RULES_PATH.stat().st_mtime)
    return rule_set


def rules_and_warnings_for_page() -> tuple:
    """Same as :func:`rules_for_page` but exposes the parser warnings.

    Used by the Validate tab to surface a "Rules-file warnings"
    expander; everyone else uses :func:`rules_for_page`.
    """
    if not _RULES_PATH.exists():
        return rules_mod.RuleSet(), []
    return _load_rules(str(_RULES_PATH), _RULES_PATH.stat().st_mtime)


def sidebar_status() -> None:
    """Render the standard left-sidebar status block.

    Every page calls this so the chrome stays identical across the app.
    """
    with st.sidebar:
        st.header("marcedit-web")
        user = session.current_user_id()
        st.caption(f"Signed in as **{user}**")
        st.divider()
        if session.has_upload():
            st.caption(f"Loaded: `{session.current_filename() or '(unnamed)'}`")
            st.caption(f"{session.record_count()} records")
        else:
            st.caption("No file loaded yet.")
