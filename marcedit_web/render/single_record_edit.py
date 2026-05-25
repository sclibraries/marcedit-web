"""Shared single-record `.mrk` inline editor.

Used by:

* :mod:`marcedit_web.render.view` — the View page's "Edit this record"
  button next to the readonly `.mrk` block.
* :mod:`marcedit_web.render.edit` — the Workspace Edit tab's over-cap
  branch, where the batch is too large for the all-records-as-one-text
  editor and we degrade to per-record editing.

The two callers need isolated session-state keys (so a draft in one
surface doesn't leak into the other) and unique widget keys (Streamlit
errors on duplicate ``key=`` values within a single page render).
That's what the ``key_prefix`` parameter handles — pass
``"view_edit"`` from View, ``"workspace_edit"`` from the Edit tab.
"""

from __future__ import annotations

from typing import Any

import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import mrk_writer, view_edit


def render_inline_edit(
    *,
    store: Any,
    index: int,
    record: Any,
    rule_set: Any,
    key_prefix: str,
) -> None:
    """Render the inline single-record editor below the current call site.

    ``index`` is 1-based (matches the cataloger-facing record numbering
    in View / Edit). ``record`` is the loaded pymarc.Record for that
    index; the helper renders it via :func:`mrk_writer.render_records_mrk`
    on open and parses it back via
    :func:`view_edit.parse_and_validate_single_record` on save.

    Session-state keys, all namespaced under ``key_prefix``:

    * ``{key_prefix}_active`` — bool, edit pane open?
    * ``{key_prefix}_index`` — int (1-based), which record was opened
    * ``{key_prefix}_text``  — str, current Ace buffer
    * ``{key_prefix}_feedback`` — (kind, message) tuple shown on next
      render after a save / error.
    """
    k_active = f"{key_prefix}_active"
    k_index = f"{key_prefix}_index"
    k_text = f"{key_prefix}_text"
    k_feedback = f"{key_prefix}_feedback"

    # Navigating to a different record while edit is open cancels the
    # previous draft — the buffer was tied to the previous index, so
    # carrying it across would silently corrupt the wrong record.
    if (
        st.session_state.get(k_active)
        and st.session_state.get(k_index) != index
    ):
        _clear_state(k_active, k_index, k_text)

    feedback = st.session_state.pop(k_feedback, None)
    if feedback:
        kind, msg = feedback
        getattr(st, kind)(msg)

    if not st.session_state.get(k_active):
        if st.button(
            "✏️ Edit this record",
            key=f"{key_prefix}_open_{index}",
            help=(
                "Open the single record above in a .mrk editor. Save "
                "commits the edit back into the loaded batch at this "
                "position. Other records aren't touched."
            ),
        ):
            st.session_state[k_active] = True
            st.session_state[k_index] = index
            st.session_state[k_text] = mrk_writer.render_records_mrk([record])
            st.rerun()
        return

    st.markdown("**Edit this record**")
    st.caption(
        "The editor uses MarcEdit `.mrk` format: `\\` represents a "
        "blank space in control fields, and `$` is the subfield "
        "delimiter. The read-only display above shows the actual MARC "
        "content. Save re-parses and validates; fatal errors block the "
        "save and surface inline below."
    )

    new_text = st_ace(
        value=st.session_state.get(k_text, ""),
        language="text",
        theme="github",
        keybinding="vscode",
        font_size=12,
        tab_size=2,
        wrap=False,
        show_gutter=True,
        show_print_margin=False,
        auto_update=False,
        min_lines=12,
        height=320,
        key=f"{key_prefix}_ace_{index}",
    )
    if new_text is not None:
        st.session_state[k_text] = new_text

    col_save, col_cancel, col_status = st.columns([1, 1, 4])
    save_clicked = col_save.button(
        "Save changes",
        type="primary",
        key=f"{key_prefix}_save_{index}",
    )
    cancel_clicked = col_cancel.button(
        "Cancel",
        key=f"{key_prefix}_cancel_{index}",
    )

    if cancel_clicked:
        _clear_state(k_active, k_index, k_text)
        st.rerun()
        return

    if save_clicked:
        text = st.session_state.get(k_text, "")
        result = view_edit.parse_and_validate_single_record(text, rule_set)
        if not result.can_save:
            col_status.error(
                f"Cannot save: {len(result.fatal_errors)} fatal error(s). "
                "See list below."
            )
            _render_validation_feedback(result)
            return
        store.replace(index - 1, result.record)
        # Stale derived state — Validate / Report / etc. cached the
        # pre-edit issue lists; drop them so the next visit re-runs.
        st.session_state["issues_cache"] = {}
        _clear_state(k_active, k_index, k_text)
        st.session_state[k_feedback] = (
            "success",
            f"Record {index} saved. Other records in the batch are unchanged.",
        )
        st.rerun()
        return

    # Live validation feedback for whatever's in the editor right now,
    # so the cataloger sees issues as they type instead of only on save.
    text = st.session_state.get(k_text, "")
    if text.strip():
        result = view_edit.parse_and_validate_single_record(text, rule_set)
        _render_validation_feedback(result)


def _clear_state(*keys: str) -> None:
    for key in keys:
        st.session_state.pop(key, None)


def _render_validation_feedback(result) -> None:
    """Render fatal / warning / info lists from a parse result."""
    if not (result.fatal_errors or result.warnings or result.info):
        return
    with st.expander(
        f"Validation: "
        f"{len(result.fatal_errors)} fatal, "
        f"{len(result.warnings)} warning, "
        f"{len(result.info)} info",
        expanded=bool(result.fatal_errors),
    ):
        if result.fatal_errors:
            st.markdown("**Fatal — blocks save**")
            for msg in result.fatal_errors:
                st.error(msg)
        if result.warnings:
            st.markdown("**Warnings**")
            for msg in result.warnings:
                st.warning(msg)
        if result.info:
            st.markdown("**Info**")
            for msg in result.info:
                st.caption(msg)
