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

import datetime as dt
import html
from typing import Any

import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import (
    collaboration,
    jobs,
    locks,
    mrk_annotations,
    mrk_writer,
    session,
    snapshot_actions,
    structured_record_editor,
    view_edit,
)
from marcedit_web.lib.audit import audit_event


def _can_edit_record(role: str | None, holds_lock: bool) -> bool:
    return role in {"owner", "editor"} and holds_lock


def _checkout_keys(
    key_prefix: str,
    index: int,
    job_id: int | None = None,
) -> tuple[str, str]:
    return (
        f"{key_prefix}_lock_{index}",
        f"record_checkout_opened_version_{job_id or 'session'}_{index}",
    )


def _record_lock_state(job_id: int, index: int) -> tuple[dict | None, bool]:
    row = locks.get_lock("record", collaboration.record_resource_id(job_id, index))
    if row and _is_expired(row["expires_at"]):
        row = None
    holds_lock = bool(row and row["holder_email"] == session.current_user_id())
    return row, holds_lock


def _is_expired(expires_at: str) -> bool:
    expiry = dt.datetime.fromisoformat(expires_at.removesuffix("Z"))
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return expiry <= now


def render_inline_edit(
    *,
    store: Any,
    index: int,
    record: Any,
    rule_set: Any,
    key_prefix: str,
    start_open: bool = False,
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
    k_draft = f"{key_prefix}_draft"
    k_mode = f"{key_prefix}_mode"
    k_user_closed = f"{key_prefix}_user_closed"
    k_preview = f"{key_prefix}_preview_before_save"
    k_pending_preview = f"{key_prefix}_pending_preview"
    k_feedback = f"{key_prefix}_feedback"
    job_id = st.session_state.get("current_job_id")
    user = session.current_user_id()
    role = jobs.get_access_role(int(job_id), user) if job_id is not None else None
    lock_row = None
    holds_lock = job_id is None
    if job_id is not None:
        lock_row, holds_lock = _record_lock_state(int(job_id), index)
        _render_checkout_controls(
            job_id=int(job_id),
            index=index,
            key_prefix=key_prefix,
            role=role,
            lock_row=lock_row,
            holds_lock=holds_lock,
        )

    # Navigating to a different record while edit is open cancels the
    # previous draft — the buffer was tied to the previous index, so
    # carrying it across would silently corrupt the wrong record.
    if st.session_state.get(k_index) not in (None, index):
        _clear_state(k_active, k_index, k_text, k_draft, k_mode, k_user_closed)

    feedback = st.session_state.pop(k_feedback, None)
    if feedback:
        kind, msg = feedback
        getattr(st, kind)(msg)

    def _open_editor() -> None:
        st.session_state[k_active] = True
        st.session_state[k_index] = index
        st.session_state[k_text] = mrk_writer.render_records_mrk([record])
        st.session_state[k_draft] = structured_record_editor.record_to_draft(
            record
        )
        st.session_state[k_mode] = "Field editor"
        st.session_state.pop(k_user_closed, None)

    if _should_open_immediately(st.session_state, k_active, start_open=start_open):
        _open_editor()

    if not st.session_state.get(k_active):
        can_open = _can_edit_record(role, holds_lock)
        disabled = job_id is not None and not can_open
        if st.button(
            "✏️ Edit this record",
            key=f"{key_prefix}_open_{index}",
            disabled=disabled,
            help=(
                "Open a one-record field editor. Save commits this "
                "record back into the loaded batch; other records aren't "
                "touched."
            ),
        ):
            _open_editor()
            st.rerun()
        return

    st.markdown("**Edit this record**")
    mode = st.radio(
        "Edit mode",
        ["Field editor", "Advanced .mrk source"],
        horizontal=True,
        key=f"{key_prefix}_mode_radio_{index}",
        index=0 if st.session_state.get(k_mode) != "Advanced .mrk source" else 1,
    )
    st.session_state[k_mode] = mode

    if mode == "Field editor":
        draft = st.session_state.setdefault(
            k_draft,
            structured_record_editor.record_to_draft(record),
        )
        can_save = _can_edit_record(role, holds_lock)
        save_disabled = job_id is not None and not can_save
        _render_jump_links(draft)
        top_save_clicked, top_cancel_clicked, preview_enabled = (
            _render_structured_action_bar(
                key_prefix,
                index,
                "top",
                preview_key=k_preview,
                include_preview=True,
                save_disabled=save_disabled,
            )
        )
        live_result = structured_record_editor.validate_draft(draft, rule_set)

        if top_cancel_clicked:
            _clear_state(k_active, k_index, k_text, k_draft, k_mode)
            st.session_state[k_user_closed] = True
            st.session_state.pop(k_pending_preview, None)
            st.rerun()
            return

        if top_save_clicked:
            if preview_enabled:
                st.session_state[k_pending_preview] = True
                st.rerun()
                return
            st.session_state.pop(k_pending_preview, None)
            if _save_validated_record(
                store=store,
                index=index,
                result=live_result,
                key_prefix=key_prefix,
                status_container=st,
                feedback_key=k_feedback,
                clear_keys=(k_active, k_index, k_text, k_draft, k_mode),
            ):
                st.rerun()
            return

        if _should_show_pending_preview(st.session_state, k_pending_preview):
            def _dismiss_preview() -> None:
                st.session_state.pop(k_pending_preview, None)
                st.rerun()

            def _confirm_preview(status_col: Any) -> None:
                if _save_validated_record(
                    store=store,
                    index=index,
                    result=live_result,
                    key_prefix=key_prefix,
                    status_container=status_col,
                    feedback_key=k_feedback,
                    clear_keys=(k_active, k_index, k_text, k_draft, k_mode),
                ):
                    st.session_state.pop(k_pending_preview, None)
                    st.rerun()

            _open_pending_preview_dialog(
                draft=draft,
                live_result=live_result,
                key_prefix=key_prefix,
                index=index,
                save_callback=_confirm_preview,
                dismiss_callback=_dismiss_preview,
            )

        section_save_clicked = _render_structured_field_editor(
            draft,
            key_prefix,
            index,
            save_disabled=save_disabled,
        )
        live_result = structured_record_editor.validate_draft(draft, rule_set)

        bottom_save_clicked, bottom_cancel_clicked, _ = (
            _render_structured_action_bar(
                key_prefix,
                index,
                "bottom",
                preview_key=k_preview,
                include_preview=False,
                save_disabled=save_disabled,
            )
        )
        save_clicked = top_save_clicked or section_save_clicked or bottom_save_clicked
        cancel_clicked = top_cancel_clicked or bottom_cancel_clicked

        if cancel_clicked:
            _clear_state(k_active, k_index, k_text, k_draft, k_mode)
            st.session_state[k_user_closed] = True
            st.session_state.pop(k_pending_preview, None)
            st.rerun()
            return

        if save_clicked:
            if preview_enabled:
                st.session_state[k_pending_preview] = True
                st.rerun()
                return
            else:
                st.session_state.pop(k_pending_preview, None)
                if _save_validated_record(
                    store=store,
                    index=index,
                    result=live_result,
                    key_prefix=key_prefix,
                    status_container=st,
                    feedback_key=k_feedback,
                    clear_keys=(k_active, k_index, k_text, k_draft, k_mode),
                ):
                    st.rerun()
                return

        _render_validation_feedback(live_result)
        return

    st.caption(
        "Advanced source mode uses MarcEdit `.mrk` format: `\\` represents "
        "a blank space in control fields, and `$` is the subfield delimiter."
    )

    # Validate the current buffer ONCE before st_ace so the result can
    # drive both the Ace gutter annotations (inline next to the
    # offending line) and the expander below. ``auto_update=False`` on
    # st_ace means the buffer in session_state lags one Apply behind
    # what the user is typing — same lag the prior expander-only path
    # had, just now visible in the gutter too.
    current_text = st.session_state.get(k_text, "")
    live_result = (
        view_edit.parse_and_validate_single_record(current_text, rule_set)
        if current_text.strip() else None
    )
    annotations = mrk_annotations.build_annotations(current_text, live_result)

    new_text = st_ace(
        value=current_text,
        language="text",
        theme="github",
        keybinding="vscode",
        font_size=12,
        tab_size=2,
        wrap=False,
        show_gutter=True,
        show_print_margin=False,
        auto_update=False,
        annotations=annotations,
        min_lines=12,
        height=320,
        key=f"{key_prefix}_ace_{index}",
    )
    if new_text is not None:
        st.session_state[k_text] = new_text

    col_save, col_cancel, col_status = st.columns([1, 1, 4])
    can_save = _can_edit_record(role, holds_lock)
    save_clicked = col_save.button(
        "Save changes",
        type="primary",
        disabled=job_id is not None and not can_save,
        key=f"{key_prefix}_save_{index}",
    )
    cancel_clicked = col_cancel.button(
        "Cancel",
        key=f"{key_prefix}_cancel_{index}",
    )

    if cancel_clicked:
        _clear_state(k_active, k_index, k_text, k_draft, k_mode)
        st.session_state[k_user_closed] = True
        st.rerun()
        return

    if save_clicked:
        # Re-validate against the freshest buffer (st_ace may have
        # returned a new value above this rerun). ``live_result`` was
        # computed BEFORE the st_ace call so it can be one Apply behind
        # the editor — we don't trust it for the save decision.
        text = st.session_state.get(k_text, "")
        result = view_edit.parse_and_validate_single_record(text, rule_set)
        if _save_validated_record(
            store=store,
            index=index,
            result=result,
            key_prefix=key_prefix,
            status_container=col_status,
            feedback_key=k_feedback,
            clear_keys=(k_active, k_index, k_text, k_draft, k_mode),
        ):
            st.rerun()
        return

    # Expander fallback below the buttons — same data as the gutter
    # annotations, in a form the cataloger can scan as a list.
    if live_result is not None:
        _render_validation_feedback(live_result)


def _clear_state(*keys: str) -> None:
    for key in keys:
        st.session_state.pop(key, None)


def _should_open_immediately(
    session_state: dict,
    active_key: str,
    *,
    start_open: bool,
) -> bool:
    """Return whether a start-open editor should initialize this render."""
    if not start_open:
        return False
    if session_state.get(active_key):
        return False
    closed_key = active_key.replace("_active", "_user_closed")
    return not session_state.get(closed_key)


def _should_show_pending_preview(session_state: dict, pending_key: str) -> bool:
    return bool(session_state.get(pending_key))


def _render_jump_links(draft: structured_record_editor.RecordDraft) -> None:
    targets = structured_record_editor.jump_targets(draft)
    if not targets:
        return
    st.markdown(_floating_jump_rail_html(targets), unsafe_allow_html=True)


def _floating_jump_rail_html(targets: list[tuple[str, str]]) -> str:
    links = "\n".join(
        (
            f'<a class="record-jump-rail-link" '
            f'href="#{_section_anchor(target)}">{html.escape(label)}</a>'
        )
        for target, label in targets
    )
    return (
        '<aside class="record-jump-rail">'
        "<details open>"
        "<summary>Jump</summary>"
        '<nav aria-label="Record sections">'
        f"{links}"
        "</nav>"
        "</details>"
        "</aside>"
        "<style>"
        ".record-jump-rail {"
        "position: fixed;"
        "top: 7rem;"
        "right: 1rem;"
        "z-index: 50;"
        "max-width: 11.5rem;"
        "font-size: 0.8rem;"
        "}"
        ".record-jump-rail details {"
        "background: rgba(255,255,255,0.97);"
        "border: 1px solid rgba(49,51,63,0.2);"
        "border-radius: 6px;"
        "box-shadow: 0 4px 18px rgba(49,51,63,0.14);"
        "padding: 0.35rem;"
        "}"
        ".record-jump-rail summary {"
        "cursor: pointer;"
        "font-weight: 650;"
        "line-height: 1.2;"
        "padding: 0.15rem 0.2rem;"
        "}"
        ".record-jump-rail nav {"
        "display: flex;"
        "flex-direction: column;"
        "gap: 0.2rem;"
        "margin-top: 0.35rem;"
        "}"
        ".record-jump-rail-link {"
        "display: block;"
        "padding: 0.2rem 0.35rem;"
        "border-radius: 4px;"
        "background: rgba(49,51,63,0.055);"
        "text-decoration: none !important;"
        "line-height: 1.15;"
        "}"
        ".record-jump-rail-link:hover {"
        "background: rgba(255,75,75,0.13);"
        "}"
        "@media (min-width: 901px) {"
        "[data-testid=\"stMainBlockContainer\"],"
        ".main .block-container {"
        "padding-right: 13rem;"
        "}"
        "}"
        "@media (max-width: 900px) {"
        ".record-jump-rail { right: 0.35rem; max-width: 8.5rem; }"
        ".record-jump-rail nav { max-height: 55vh; overflow-y: auto; }"
        "}"
        "</style>"
    )


def _open_pending_preview_dialog(
    *,
    draft: structured_record_editor.RecordDraft,
    live_result: view_edit.SingleRecordParseResult,
    key_prefix: str,
    index: int,
    save_callback: Any,
    dismiss_callback: Any,
) -> None:
    _record_save_preview_dialog(
        draft=draft,
        live_result=live_result,
        key_prefix=key_prefix,
        index=index,
        save_callback=save_callback,
        dismiss_callback=dismiss_callback,
    )


@st.dialog("Preview record before saving", width="large")
def _record_save_preview_dialog(
    draft: structured_record_editor.RecordDraft,
    live_result: view_edit.SingleRecordParseResult,
    key_prefix: str,
    index: int,
    save_callback: Any,
    dismiss_callback: Any,
) -> None:
    if live_result.can_save:
        st.code(
            structured_record_editor.preview_mrk(draft),
            language="text",
        )
    else:
        _render_validation_feedback(live_result)
    confirm_col, dismiss_col, status_col = st.columns([1, 1, 4])
    confirm_clicked = confirm_col.button(
        "Confirm save",
        type="primary",
        disabled=not live_result.can_save,
        key=f"{key_prefix}_confirm_preview_{index}",
    )
    dismiss_clicked = dismiss_col.button(
        "Keep editing",
        key=f"{key_prefix}_dismiss_preview_{index}",
    )
    if dismiss_clicked:
        dismiss_callback()
        return
    if confirm_clicked:
        save_callback(status_col)


def _section_anchor(target: str) -> str:
    return f"record-field-{target.lower()}"


def _render_anchor(target: str) -> None:
    st.markdown(
        f'<a id="{_section_anchor(target)}"></a>',
        unsafe_allow_html=True,
    )


def _render_structured_action_bar(
    key_prefix: str,
    index: int,
    suffix: str,
    *,
    preview_key: str,
    include_preview: bool,
    save_disabled: bool,
) -> tuple[bool, bool, bool]:
    cols = st.columns([1, 1, 2, 3])
    save_clicked = cols[0].button(
        "Save changes",
        type="primary",
        disabled=save_disabled,
        key=f"{key_prefix}_structured_save_{suffix}_{index}",
    )
    cancel_clicked = cols[1].button(
        "Cancel",
        key=f"{key_prefix}_structured_cancel_{suffix}_{index}",
    )
    preview_enabled = bool(st.session_state.get(preview_key, False))
    if include_preview:
        preview_enabled = cols[2].checkbox(
            "Preview before saving",
            key=preview_key,
            value=preview_enabled,
        )
    return save_clicked, cancel_clicked, preview_enabled


def _render_section_save(
    key_prefix: str,
    index: int,
    suffix: str,
    *,
    disabled: bool,
) -> bool:
    return st.button(
        "Save changes",
        type="primary",
        disabled=disabled,
        key=f"{key_prefix}_section_save_{index}_{suffix}",
    )


def _save_validated_record(
    *,
    store: Any,
    index: int,
    result: view_edit.SingleRecordParseResult,
    key_prefix: str,
    status_container: Any,
    feedback_key: str,
    clear_keys: tuple[str, ...],
) -> bool:
    """Save a validated single-record edit through shared safeguards."""
    if not result.can_save:
        status_container.error(
            f"Cannot save: {len(result.fatal_errors)} fatal error(s). "
            "See list below."
        )
        _render_validation_feedback(result)
        return False

    job_id = st.session_state.get("current_job_id")
    user = session.current_user_id()
    if job_id is not None:
        _, version_key = _checkout_keys(key_prefix, index, int(job_id))
        opened_version = st.session_state.get(version_key)
        if opened_version is None:
            status_container.error("Cannot save: record checkout is missing.")
            return False
        try:
            collaboration.assert_can_save_record(
                int(job_id),
                index,
                user,
                int(opened_version),
            )
        except collaboration.CollaborationError as exc:
            status_container.error(f"Cannot save: {exc}")
            return False

    before_bytes = store.to_mrc_bytes()
    store.replace(index - 1, result.record)
    after_bytes = store.to_mrc_bytes()
    snapshot = snapshot_actions.record_edit_snapshot(
        job_id=st.session_state.get("current_job_id"),
        user_email=session.current_user_id(),
        label=f"Single record edit #{index}",
        before_bytes=before_bytes,
        after_bytes=after_bytes,
        record_index=index,
        source=key_prefix,
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
    _clear_state(*clear_keys)
    st.session_state[feedback_key] = (
        "success",
        f"Record {index} saved. Other records in the batch are unchanged.",
    )
    return True


def _render_structured_field_editor(
    draft: structured_record_editor.RecordDraft,
    key_prefix: str,
    index: int,
    *,
    save_disabled: bool,
) -> bool:
    """Render editable MARC field rows for a single-record draft."""
    save_clicked = False
    _render_anchor("fixed")
    draft.leader = st.text_input(
        "Leader",
        value=draft.leader,
        max_chars=24,
        key=f"{key_prefix}_leader_{index}",
    )

    st.markdown("**Control fields**")
    for pos, field in enumerate(list(draft.control_fields)):
        cols = st.columns([1, 5, 1])
        field.tag = cols[0].text_input(
            "Tag",
            value=field.tag,
            max_chars=3,
            key=f"{key_prefix}_control_tag_{index}_{pos}",
        )
        field.data = cols[1].text_input(
            "Data",
            value=field.data,
            key=f"{key_prefix}_control_data_{index}_{pos}",
        )
        if cols[2].button(
            "Delete",
            key=f"{key_prefix}_control_delete_{index}_{pos}",
        ):
            del draft.control_fields[pos]
            st.rerun()

    if st.button("Add control field", key=f"{key_prefix}_add_control_{index}"):
        draft.control_fields.append(
            structured_record_editor.ControlFieldDraft(tag="001", data="")
        )
        st.rerun()
    save_clicked = (
        _render_section_save(
            key_prefix,
            index,
            "fixed",
            disabled=save_disabled,
        )
        or save_clicked
    )

    st.markdown("**Variable fields**")
    for pos, field in enumerate(list(draft.variable_fields)):
        if pos == 0 or draft.variable_fields[pos - 1].tag != field.tag:
            _render_anchor(field.tag)
        with st.container(border=True):
            top = st.columns([1, 1, 1, 1, 1, 1])
            field.tag = top[0].text_input(
                "Tag",
                value=field.tag,
                max_chars=3,
                key=f"{key_prefix}_var_tag_{index}_{pos}",
            )
            field.ind1 = top[1].text_input(
                "Ind 1",
                value=field.ind1,
                max_chars=1,
                key=f"{key_prefix}_var_ind1_{index}_{pos}",
            )
            field.ind2 = top[2].text_input(
                "Ind 2",
                value=field.ind2,
                max_chars=1,
                key=f"{key_prefix}_var_ind2_{index}_{pos}",
            )
            if top[3].button(
                "Move up",
                key=f"{key_prefix}_var_up_{index}_{pos}",
            ):
                if pos > 0:
                    draft.variable_fields[pos - 1], draft.variable_fields[pos] = (
                        draft.variable_fields[pos],
                        draft.variable_fields[pos - 1],
                    )
                    st.rerun()
            if top[4].button(
                "Move down",
                key=f"{key_prefix}_var_down_{index}_{pos}",
            ):
                if pos < len(draft.variable_fields) - 1:
                    draft.variable_fields[pos + 1], draft.variable_fields[pos] = (
                        draft.variable_fields[pos],
                        draft.variable_fields[pos + 1],
                    )
                    st.rerun()
            if top[5].button("Delete", key=f"{key_prefix}_var_delete_{index}_{pos}"):
                del draft.variable_fields[pos]
                st.rerun()

            for sub_pos, subfield in enumerate(list(field.subfields)):
                cols = st.columns([1, 6, 1])
                subfield.code = cols[0].text_input(
                    "Code",
                    value=subfield.code,
                    max_chars=1,
                    key=f"{key_prefix}_sub_code_{index}_{pos}_{sub_pos}",
                )
                subfield.value = cols[1].text_input(
                    "Value",
                    value=subfield.value,
                    key=f"{key_prefix}_sub_value_{index}_{pos}_{sub_pos}",
                )
                if cols[2].button(
                    "Delete",
                    key=f"{key_prefix}_sub_delete_{index}_{pos}_{sub_pos}",
                ):
                    del field.subfields[sub_pos]
                    st.rerun()

            if st.button("Add subfield", key=f"{key_prefix}_add_sub_{index}_{pos}"):
                field.subfields.append(
                    structured_record_editor.SubfieldDraft(code="a", value="")
                )
                st.rerun()
            save_clicked = (
                _render_section_save(
                    key_prefix,
                    index,
                    f"variable_{pos}",
                    disabled=save_disabled,
                )
                or save_clicked
            )

    if st.button("Add variable field", key=f"{key_prefix}_add_variable_{index}"):
        draft.variable_fields.append(
            structured_record_editor.VariableFieldDraft(
                tag="500",
                ind1=" ",
                ind2=" ",
                subfields=[
                    structured_record_editor.SubfieldDraft(code="a", value="")
                ],
            )
        )
        st.rerun()
    return save_clicked


def _render_checkout_controls(
    *,
    job_id: int,
    index: int,
    key_prefix: str,
    role: str | None,
    lock_row: dict | None,
    holds_lock: bool,
) -> None:
    lock_key, version_key = _checkout_keys(key_prefix, index, job_id)
    if role not in {"owner", "editor"}:
        st.info("This shared job is read-only for your account.")
        return

    if lock_row and not holds_lock:
        st.warning(
            "Record is checked out by "
            f"{lock_row['holder_email']} until {lock_row['expires_at']}."
        )
        return

    cols = st.columns([1, 1, 4])
    if holds_lock:
        cols[2].caption(
            f"Checked out by you until {lock_row['expires_at'] if lock_row else 'expiry'}."
        )
        if cols[1].button("Release checkout", key=f"{lock_key}_release"):
            collaboration.release_record_lock(job_id, index, session.current_user_id())
            st.session_state.pop(version_key, None)
            st.rerun()
        return

    if cols[0].button("Check out record", key=f"{lock_key}_acquire"):
        try:
            decision = collaboration.acquire_record_lock(
                job_id,
                index,
                session.current_user_id(),
            )
        except collaboration.CollaborationError as exc:
            st.error(str(exc))
            return
        if decision.acquired:
            st.session_state[version_key] = collaboration.current_job_version(job_id)
            st.rerun()
        else:
            st.warning(
                "Record is checked out by "
                f"{decision.holder_email} until {decision.expires_at}."
            )


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
