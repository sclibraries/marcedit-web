"""Workspace — one place to do the whole loaded-file workflow.

The cataloger's original complaint: "the UI organization needs to be
improved as there is a lot of clicking. We could condense several of the
toolbar functions on the left into MarcEditor for simplicity. For
example, when a marc file is opened one place where we can view,
validate, see report data, edit, and trigger a tasks would be better
than jumping around to multiple views."

This page bundles View / Validate / Report / Tasks / Edit / Diff into
tabs that share the same loaded batch. The per-page deep links still
work — they call the same render functions from ``marcedit_web.render.*``.
"""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import (
    dedupe,
    edit,
    loaded_batch_status,
    report,
    rules_and_warnings_for_page,
    sidebar_status,
    tasks as render_tasks,
    validate,
    view,
)
from marcedit_web.render import diff as render_diff

session.init_page()

st.title("Workspace")
st.caption(
    "Edit / View / Validate / Report / Tasks / Diff on the loaded batch — "
    "one page instead of six clicks."
)

sidebar_status()
loaded_batch_status()


# --- Tabs -----------------------------------------------------------------


(
    tab_edit,
    tab_view,
    tab_validate,
    tab_report,
    tab_tasks,
    tab_dedupe,
    tab_diff,
) = st.tabs(["Edit", "View", "Validate", "Report", "Tasks", "Dedupe", "Diff"])

rule_set, rules_warnings = rules_and_warnings_for_page()

with tab_edit:
    edit.render(rule_set)

with tab_view:
    view.render(rule_set)

with tab_validate:
    validate.render(rule_set, rules_warnings)

with tab_report:
    report.render()

with tab_tasks:
    render_tasks.render()

with tab_dedupe:
    dedupe.render()

with tab_diff:
    render_diff.render()
