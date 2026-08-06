"""Shared task-operation reference data and rendering helpers."""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping

import streamlit as st

from marcedit_web.lib import operation_reference, task_builder


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
    entries = operation_reference.search_entries(query if needle else "")
    if not include_custom:
        entries = [entry for entry in entries if entry["kind"] != "custom"]
    # Preserve the existing palette parameter shape for dialog callers while
    # adding the canonical explanatory sections.
    palette_by_kind = {
        entry["kind"]: entry for entry in task_builder.OPERATIONS_PALETTE
    }
    merged = []
    for entry in entries:
        combined = copy.deepcopy(entry)
        palette_entry = palette_by_kind.get(entry["kind"])
        combined["params"] = copy.deepcopy(
            palette_entry["params"] if palette_entry is not None else []
        )
        merged.append(combined)
    return merged


def render_reference_entry(entry: Mapping[str, Any]) -> None:
    """Render facts for one operation from the shared palette."""

    canonical = (
        entry
        if entry.get("source") == "quick"
        else operation_reference.REFERENCE_REGISTRY.get(entry["kind"], entry)
    )
    st.markdown("**{0}**".format(canonical["label"]))
    st.caption("Operation kind: `{0}`".format(entry["kind"]))
    st.write(canonical["purpose"])
    st.write("**When to use:** {0}".format(canonical["when_to_use"]))
    st.write("**Inputs:** {0}".format(", ".join(canonical["inputs"]) or "none"))
    st.write("**Behavior:** {0}".format(canonical["behavior"]))
    st.write("**Preserves:** {0}".format(canonical["preserves"]))
    st.write("**Skip behavior:** {0}".format(canonical["skip_behavior"]))
    st.write("**Error behavior:** {0}".format(canonical["error_behavior"]))
    example = canonical["example"]
    st.code("Before: {0}\nAfter: {1}".format(example["before"], example["after"]))
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
