"""Streamlit renderers for fixed-field structured editors.

The lib layers (:mod:`marcedit_web.lib.fixed_field_008` and
:mod:`marcedit_web.lib.fixed_field_control`) own schema + parse / apply logic.
This module is the thin Streamlit binding — same shape as
:mod:`single_record_edit`:

* a ``key_prefix`` so View and the Workspace Edit tab can both
  embed the helper without colliding session-state keys;
* an ``st.expander`` host so the helper stays out of the way until
  the cataloger opens it;
* widgets selected per position descriptor — ``st.selectbox`` for
  enums, ``st.text_input`` for free-form ranges.

Save commits via ``store.replace(index - 1, record)``. Cancel drops
draft state.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from marcedit_web.lib import fixed_field_control as ffc
from marcedit_web.lib import fixed_field_008 as ff
from marcedit_web.lib import session, snapshot_actions
from marcedit_web.lib.audit import audit_event


def render_fixed_field_helper(
    *,
    store: Any,
    index: int,
    record: Any,
    key_prefix: str,
) -> None:
    """Render structured controls for LDR, 006, and 007."""
    parsed = ffc.parse_fixed_fields(record)

    with st.expander("LDR / 006 / 007 helper", expanded=False):
        st.caption(
            "Edit common fixed-field bytes with labels. Save writes the "
            "selected byte changes back to this record only; the raw `.mrk` "
            "editor remains available for fields not covered here."
        )

        draft_key = f"{key_prefix}_fixed_draft_{index}"
        feedback_key = f"{key_prefix}_fixed_feedback"
        initial = {
            pos.id: pos.value
            for positions in parsed.values()
            for pos in positions
        }
        draft = st.session_state.setdefault(draft_key, initial)

        for tag in ("LDR", "006", "007"):
            positions = parsed.get(tag, [])
            st.markdown(f"**{tag}**")
            if not positions:
                st.info(f"{tag} is not present or has no supported editable positions.")
                continue

            cols = st.columns(2)
            for i, pos in enumerate(positions):
                with cols[i % 2]:
                    draft[pos.id] = _render_fixed_widget(
                        pos,
                        draft.get(pos.id, pos.value),
                        key=f"{key_prefix}_fixed_{pos.id}_{index}",
                    )

        feedback = st.session_state.pop(feedback_key, None)
        if feedback:
            kind, msg = feedback
            getattr(st, kind)(msg)

        save_col, cancel_col, _ = st.columns([1, 1, 4])
        save_clicked = save_col.button(
            "Save fixed fields",
            type="primary",
            key=f"{key_prefix}_fixed_save_{index}",
        )
        cancel_clicked = cancel_col.button(
            "Cancel",
            key=f"{key_prefix}_fixed_cancel_{index}",
        )

        if cancel_clicked:
            st.session_state.pop(draft_key, None)
            st.rerun()
            return

        if save_clicked:
            try:
                before_bytes = store.to_mrc_bytes()
                ffc.apply_fixed_field_updates(record, dict(draft))
            except ValueError as exc:
                st.error(f"Fixed fields not saved: {exc}")
                return
            store.replace(index - 1, record)
            after_bytes = store.to_mrc_bytes()
            snapshot = snapshot_actions.record_edit_snapshot(
                job_id=st.session_state.get("current_job_id"),
                user_email=session.current_user_id(),
                label=f"LDR/006/007 edit #{index}",
                before_bytes=before_bytes,
                after_bytes=after_bytes,
                record_index=index,
                source=f"{key_prefix}-fixed-field-helper",
            )
            if snapshot is not None:
                audit_event(
                    "job-snapshot-created",
                    user=session.current_user_id(),
                    snapshot_id=snapshot["id"],
                    job_id=snapshot["job_id"],
                    kind=snapshot["kind"],
                )
            st.session_state["issues_cache"] = {}
            st.session_state.pop(draft_key, None)
            st.session_state[feedback_key] = (
                "success",
                f"Record {index}'s fixed fields saved. Other records unchanged.",
            )
            st.rerun()


def render_008_helper(
    *,
    store: Any,
    index: int,
    record: Any,
    key_prefix: str,
) -> None:
    """Render the 008 structured-edit expander for the current record.

    ``index`` is 1-based (matches View / Edit navigator). ``record``
    is the loaded pymarc.Record at that index. ``key_prefix`` should
    be unique across callers so session-state and widget keys don't
    collide ("view_008" vs "workspace_008", etc).

    Behavior summary:

    * Records with material type out of scope (music, maps, etc.) show
      a friendly note explaining the helper is BK/CR-only today.
    * Records without an 008 surface a note pointing the cataloger
      at the inline ``.mrk`` editor to add one.
    * Otherwise: per-position widget + Save / Cancel.
    """
    material, parsed = ff.parse_008(record)

    with st.expander("008 Fixed-Field helper", expanded=False):
        if material is None:
            st.info(
                "The 008 helper currently covers **Books (BK)** and "
                "**Continuing Resources (CR)**. This record's leader "
                "(byte 06 / 07) doesn't match either; use the inline "
                "`.mrk` editor above to edit the 008 directly."
            )
            return
        if not parsed:
            st.info(
                f"This record is a **{ff.MATERIAL_LABELS.get(material, material)}** "
                "but has no 008 field yet. Add an `=008  ` line via the inline "
                "`.mrk` editor above first, then reopen this helper to edit it."
            )
            return

        st.caption(
            f"Material type: **{ff.MATERIAL_LABELS.get(material, material)}** "
            "(detected from leader bytes 06 / 07). Save writes the "
            "recomposed 40-byte 008 back at this record's position; "
            "other records are unchanged."
        )

        # Session-state slot for the draft, namespaced under key_prefix
        # AND keyed by the record's identity so navigating away resets
        # the draft cleanly. ``index`` participates in the key for the
        # same reason.
        draft_key = f"{key_prefix}_draft_{index}"
        feedback_key = f"{key_prefix}_feedback"
        draft = st.session_state.setdefault(
            draft_key, {p.position.id: p.value for p in parsed}
        )

        # Render widgets in two columns to keep the expander compact.
        col_left, col_right = st.columns(2)
        for i, pp in enumerate(parsed):
            target_col = col_left if i % 2 == 0 else col_right
            with target_col:
                draft[pp.position.id] = _render_widget(
                    pp.position, draft.get(pp.position.id, pp.value),
                    key=f"{key_prefix}_{pp.position.id}_{index}",
                )

        feedback = st.session_state.pop(feedback_key, None)
        if feedback:
            kind, msg = feedback
            getattr(st, kind)(msg)

        save_col, cancel_col, _ = st.columns([1, 1, 4])
        save_clicked = save_col.button(
            "Save 008",
            type="primary",
            key=f"{key_prefix}_save_{index}",
        )
        cancel_clicked = cancel_col.button(
            "Cancel",
            key=f"{key_prefix}_cancel_{index}",
        )

        if cancel_clicked:
            st.session_state.pop(draft_key, None)
            st.rerun()
            return

        if save_clicked:
            try:
                before_bytes = store.to_mrc_bytes()
                ff.apply_008(record, dict(draft))
            except ValueError as exc:
                st.error(f"008 not saved: {exc}")
                return
            store.replace(index - 1, record)
            after_bytes = store.to_mrc_bytes()
            snapshot = snapshot_actions.record_edit_snapshot(
                job_id=st.session_state.get("current_job_id"),
                user_email=session.current_user_id(),
                label=f"008 edit #{index}",
                before_bytes=before_bytes,
                after_bytes=after_bytes,
                record_index=index,
                source=f"{key_prefix}-008-helper",
            )
            if snapshot is not None:
                audit_event(
                    "job-snapshot-created",
                    user=session.current_user_id(),
                    snapshot_id=snapshot["id"],
                    job_id=snapshot["job_id"],
                    kind=snapshot["kind"],
                )
            st.session_state["issues_cache"] = {}
            st.session_state.pop(draft_key, None)
            st.session_state[feedback_key] = (
                "success",
                f"Record {index}'s 008 saved. Other records unchanged.",
            )
            st.rerun()


def _render_widget(pos: ff.Position, current: str, *, key: str) -> str:
    """Pick a widget for the position and return its current value."""
    if pos.allowed is None:
        # Free-form chunk: ``max_chars`` keeps the cataloger from
        # over-typing past the position's declared length.
        return st.text_input(
            pos.label,
            value=current,
            max_chars=pos.length,
            help=f"{pos.help} ({pos.length}-char range, bytes {pos.start}–{pos.end - 1})",
            key=key,
        )

    # Enum: render a selectbox. Labels include the code so catalogers
    # see what gets written. ``current`` may be a value outside the
    # allowed list (legacy data); we add an "(existing)" pseudo-option
    # at the top so it's not silently dropped.
    options = pos.values() or []
    labels = {code: label for code, label in pos.allowed or []}
    if current not in options:
        options = [current] + options
        labels[current] = f"(existing: {current!r})"
    index = options.index(current) if current in options else 0
    return st.selectbox(
        pos.label,
        options=options,
        index=index,
        format_func=lambda code: f"{code!r} — {labels.get(code, code)}",
        help=f"{pos.help} (byte {pos.start}{' ' if pos.length == 1 else f' – {pos.end - 1}'})",
        key=key,
    )


def _render_fixed_widget(pos: ffc.FixedPosition, current: str, *, key: str) -> str:
    """Render one LDR/006/007 position widget."""
    if not pos.allowed:
        return st.text_input(
            pos.label,
            value=current,
            max_chars=pos.length,
            help=f"{pos.help} ({pos.length}-char range, bytes {pos.start}-{pos.end - 1})",
            key=key,
        )

    options = pos.values()
    labels = {code: label for code, label in pos.allowed}
    if current not in options:
        options = [current] + options
        labels[current] = f"(existing: {current!r})"
    option_index = options.index(current) if current in options else 0
    return st.selectbox(
        pos.label,
        options=options,
        index=option_index,
        format_func=lambda code: f"{code!r} — {labels.get(code, code)}",
        help=f"{pos.help} (byte {pos.start})",
        key=key,
    )
