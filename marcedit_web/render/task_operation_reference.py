"""Shared task-operation reference data and rendering helpers."""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping

import streamlit as st

from marcedit_web.lib import task_builder


_SYNTAX_KINDS = {"add-field", "build-field", "guided-find-replace"}
_SYNTAX_URL = (
    "https://github.com/sclibraries/marcedit-web/blob/main/"
    "docs/task-authoring-syntax.md"
)


def reference_entries(
    *,
    include_custom: bool,
    query: str = "",
) -> list[dict[str, Any]]:
    """Return copied palette entries in searchable display order."""

    needle = query.strip().casefold()
    entries = copy.deepcopy(task_builder.OPERATIONS_PALETTE)
    if not include_custom:
        entries = [entry for entry in entries if entry["kind"] != "custom"]
    if needle:
        entries = [
            entry
            for entry in entries
            if needle
            in "{0} {1}".format(
                entry["label"],
                entry["summary"],
            ).casefold()
        ]
    return sorted(entries, key=lambda entry: entry["label"].casefold())


def render_reference_entry(entry: Mapping[str, Any]) -> None:
    """Render facts for one operation from the shared palette."""

    st.markdown("**{0}**".format(entry["label"]))
    st.caption("Operation kind: `{0}`".format(entry["kind"]))
    st.write(entry["summary"])
    if entry["kind"] in _SYNTAX_KINDS:
        st.caption(
            "[docs/task-authoring-syntax.md]({0})".format(_SYNTAX_URL)
        )


def render_reference_browser(
    *,
    include_custom: bool,
    key_prefix: str,
) -> None:
    """Render a searchable list of operation-reference entries."""

    query = st.text_input(
        "Search operations",
        key="{0}_search".format(key_prefix),
    )
    for entry in reference_entries(
        include_custom=include_custom,
        query=query,
    ):
        render_reference_entry(entry)


def open_reference_dialog(
    *, include_custom: bool, on_close: Callable[[], None]
) -> None:
    """Open the standalone operation-reference dialog."""

    def render() -> None:
        render_reference_browser(
            include_custom=include_custom,
            key_prefix="tasks_operation_reference",
        )
        if st.button("Close", key="tasks_operation_reference_close"):
            on_close()
            st.rerun()

    st.dialog(
        "Operation reference",
        width="large",
        dismissible=False,
    )(render)()
