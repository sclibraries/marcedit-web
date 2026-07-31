"""Transactional Add/Edit dialog for structured task operations."""

from __future__ import annotations

import copy
import inspect
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional, Sequence

import streamlit as st
from streamlit.errors import StreamlitAPIException

from marcedit_web.lib import task_authoring, task_builder
from marcedit_web.render import task_authoring as task_authoring_render
from marcedit_web.render import task_operation_reference


@dataclass
class OperationDialogState:
    mode: str
    source_index: Optional[int]
    selected_kind: Optional[str]
    opening_value: Optional[dict[str, Any]]
    working_copy: Optional[dict[str, Any]]
    nonce: int
    discard_pending: bool = False


def new_add_state(nonce: int) -> OperationDialogState:
    return OperationDialogState(
        mode="add",
        source_index=None,
        selected_kind=None,
        opening_value=None,
        working_copy=None,
        nonce=nonce,
    )


def new_edit_state(
    operation: dict[str, Any],
    *,
    index: int,
    nonce: int,
) -> OperationDialogState:
    return OperationDialogState(
        mode="edit",
        source_index=index,
        selected_kind=str(operation.get("kind") or ""),
        opening_value=copy.deepcopy(operation),
        working_copy=copy.deepcopy(operation),
        nonce=nonce,
    )


def _palette_entry(kind: str):
    return next(
        (
            entry
            for entry in task_builder.OPERATIONS_PALETTE
            if entry["kind"] == kind
        ),
        None,
    )


def default_params_for(kind: str) -> dict[str, Any]:
    if kind == "guided-find-replace":
        return {
            "target_kind": "subfield",
            "tag": "",
            "subfield": "",
            "match_mode": "contains",
            "find": "",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": "",
            "occurrences": "all",
            "value_scope": "all",
            "condition": "always",
        }
    entry = _palette_entry(kind)
    if entry is None:
        return {}
    params = {}
    for parameter in entry["params"]:
        if "default" in parameter:
            params[parameter["name"]] = parameter["default"]
        elif parameter["type"] == "bool":
            params[parameter["name"]] = False
        elif parameter["type"] == "subfields":
            params[parameter["name"]] = []
        else:
            params[parameter["name"]] = ""
    if kind in {"add-field", "build-field"}:
        return task_authoring.normalize_operation(
            {"kind": kind, "params": params}
        )["params"]
    return params


def select_add_kind(
    state: OperationDialogState,
    kind: str,
) -> OperationDialogState:
    if state.mode != "add":
        raise ValueError("operation kind can only be selected while adding")
    return replace(
        state,
        selected_kind=kind,
        working_copy={"kind": kind, "params": default_params_for(kind)},
        discard_pending=False,
    )


def keep_in_task(
    operations: Sequence[dict[str, Any]],
    state: OperationDialogState,
) -> list[dict[str, Any]]:
    if state.working_copy is None:
        raise ValueError("select an operation before keeping it")
    kept = copy.deepcopy(list(operations))
    draft = copy.deepcopy(state.working_copy)
    if state.mode == "add":
        kept.append(draft)
        return kept
    if (
        state.mode != "edit"
        or state.source_index is None
        or state.source_index < 0
        or state.source_index >= len(kept)
    ):
        raise ValueError("the edited operation is no longer in the task")
    kept[state.source_index] = draft
    return kept


def cancel_result(state: OperationDialogState) -> str:
    return "confirm" if state.working_copy != state.opening_value else "close"


def dialog_contract_error(dialog_callable=None) -> Optional[str]:
    candidate = dialog_callable or st.dialog
    if "dismissible" not in inspect.signature(candidate).parameters:
        return (
            "Task operation dialogs require Streamlit's non-dismissible "
            "dialog contract (streamlit>=1.50,<2)."
        )
    return None


def rerun_fragment_or_app() -> None:
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def render_param_input(
    parameter: dict,
    params: dict,
    *,
    key_prefix: str,
    is_admin: bool = False,
) -> None:
    """Render one palette-defined input while preserving malformed values."""

    name = parameter["name"]
    label = parameter["label"]
    parameter_type = parameter["type"]
    help_text = parameter.get("help") or parameter.get("placeholder") or None
    key = "{0}_{1}".format(key_prefix, name)
    current = params.get(name, parameter.get("default", ""))

    if parameter_type == "text":
        params[name] = st.text_input(
            label,
            value=current,
            placeholder=parameter.get("placeholder", ""),
            help=help_text,
            key=key,
        )
    elif parameter_type == "bool":
        params[name] = st.checkbox(
            label, value=bool(current), help=help_text, key=key
        )
    elif parameter_type == "indicator":
        params[name] = st.text_input(
            label,
            value=str(current)[:1] or " ",
            max_chars=1,
            help=help_text or "Single character; space for blank.",
            key=key,
        )
    elif parameter_type == "subfield_code":
        params[name] = st.text_input(
            label,
            value=str(current)[:1],
            max_chars=1,
            help=help_text or "Single character: a-z or 0-9.",
            key=key,
        )
    elif parameter_type == "subfields":
        raw = st.text_area(
            label,
            value=json.dumps(current or [], ensure_ascii=False, indent=2),
            help=(
                'JSON list of [code, value] pairs. Example: '
                '`[["a", "Title"], ["c", "by Author"]]`. '
                + (help_text or "")
            ),
            key=key,
        )
        try:
            params[name] = json.loads(raw)
        except json.JSONDecodeError:
            st.warning(
                "`{0}`: not valid JSON; previous value preserved.".format(
                    label
                )
            )
    elif parameter_type == "select":
        options = [option["value"] for option in parameter.get("options", [])]
        labels = {
            option["value"]: option["label"]
            for option in parameter.get("options", [])
        }
        if current not in options and options:
            current = options[0]
        params[name] = st.selectbox(
            label,
            options=options,
            index=options.index(current) if current in options else 0,
            format_func=lambda value: labels.get(value, value),
            help=help_text,
            key=key,
        )
    elif parameter_type == "code":
        if is_admin:
            params[name] = st.text_area(
                label,
                value=str(current or ""),
                help=help_text or "Raw Python; runs in the sandbox.",
                key=key,
                height=200,
            )
        else:
            st.caption(
                "**{0}** — read-only (admin Code-view required to edit)".format(
                    label
                )
            )
            st.code(str(current or "# (empty)"), language="python")
    else:
        st.warning(
            "Unsupported param type `{0}` for {1}.".format(
                parameter_type, name
            )
        )


def _key(state: OperationDialogState, suffix: str) -> str:
    return "task_operation_dialog_{0}_{1}".format(state.nonce, suffix)


def _technical_form_required(
    operation: dict[str, Any],
    entry,
) -> bool:
    return (
        entry is None
        or bool(operation.get("authoring_error"))
        or operation.get("kind")
        in {"add-field", "build-field", "guided-find-replace", "custom"}
    )


def _preview_required(operation: dict[str, Any], entry) -> bool:
    return (
        entry is not None
        and not operation.get("authoring_error")
        and operation.get("kind")
        in {"add-field", "build-field", "guided-find-replace"}
    )


def render_selected_operation(
    state: OperationDialogState,
    *,
    is_admin: bool,
) -> None:
    """Delegate Set up controls without replacing the modal draft."""

    operation = state.working_copy
    if operation is None:
        return
    entry = _palette_entry(str(operation.get("kind") or ""))
    authoring_error = str(operation.get("authoring_error") or "")
    params = operation.get("params")
    if entry is None or authoring_error or not isinstance(params, dict):
        message = authoring_error or (
            "This operation is not supported. Its technical values are "
            "preserved; remove it or replace it with a supported operation."
        )
        st.error(message)
        return
    kind = operation["kind"]
    key_prefix = _key(state, "setup")
    if kind == "add-field":
        task_authoring_render.render_add_field_params(
            params, key_prefix=key_prefix, rerun=rerun_fragment_or_app
        )
    elif kind == "build-field":
        task_authoring_render.render_build_field_params(
            params, key_prefix=key_prefix, rerun=rerun_fragment_or_app
        )
    elif kind == "guided-find-replace":
        task_authoring_render.render_guided_find_replace_params(
            params, key_prefix=key_prefix, rerun=rerun_fragment_or_app
        )
    else:
        for parameter in entry["params"]:
            render_param_input(
                parameter,
                params,
                key_prefix=key_prefix,
                is_admin=is_admin,
            )


def _render_preview(
    state: OperationDialogState,
    *,
    store,
    previews: dict,
) -> None:
    operation = state.working_copy
    if operation is None:
        return
    if operation.get("kind") == "guided-find-replace":
        task_authoring_render.render_guided_replace_preview(
            operation,
            store,
            previews,
            key_prefix=_key(state, "preview"),
        )
        discard_count = (
            task_authoring_render.guided_replace_previewed_discard_count(
                operation, store, previews
            )
        )
        st.caption(
            task_authoring.describe_guided_replace(
                operation,
                previewed_discard_count=discard_count,
            )
        )
        return
    preview_record = (
        store.get(0)
        if store is not None and store.count()
        else None
    )
    task_authoring_render.render_operation_explanation(
        operation, preview_record
    )


def _render_technical(operation: dict[str, Any]) -> None:
    if (
        operation.get("kind") == "guided-find-replace"
        and not operation.get("authoring_error")
    ):
        task_authoring_render.render_guided_replace_technical_details(
            operation
        )
    st.json(operation)


def _render_reference(entry, *, include_custom: bool) -> None:
    if entry is not None:
        task_operation_reference.render_reference_entry(entry)
        return
    for reference_entry in task_operation_reference.reference_entries(
        include_custom=include_custom
    ):
        task_operation_reference.render_reference_entry(reference_entry)


def _render_with_draft_restore(
    state: OperationDialogState,
    render: Callable[[], None],
) -> None:
    """Restore the modal draft when a bounded renderer failure occurs."""

    snapshot = copy.deepcopy(state.working_copy)
    try:
        render()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        state.working_copy = snapshot
        st.error("This operation could not be displayed: {0}".format(exc))


def render_active_dialog(
    state: OperationDialogState,
    *,
    operations: Sequence[dict[str, Any]],
    is_admin: bool,
    store,
    previews: dict,
    on_keep: Callable[[list[dict[str, Any]]], None],
    on_close: Callable[[], None],
) -> None:
    """Render exactly one non-dismissible dialog around the active draft."""

    operation = state.working_copy
    entry = (
        _palette_entry(str(operation.get("kind") or ""))
        if operation is not None
        else None
    )
    if state.mode == "add" and operation is None:
        title = "Add operation"
    else:
        label = str(entry["label"]) if entry is not None else str(
            (operation or {}).get("kind") or "operation"
        )
        title = "{0} — {1}".format(state.mode.title(), label)

    def render_function() -> None:
        current_operation = state.working_copy
        current_entry = (
            _palette_entry(str(current_operation.get("kind") or ""))
            if current_operation is not None
            else None
        )
        tab_labels = ["Workspace"]
        if current_operation is not None and _technical_form_required(
            current_operation, current_entry
        ):
            tab_labels.append("Technical details")
        tab_labels.append("Reference")
        tabs = dict(zip(tab_labels, st.tabs(tab_labels)))

        with tabs["Workspace"]:
            if state.mode == "add" and state.working_copy is None:
                palette = sorted(
                    task_builder.OPERATIONS_PALETTE,
                    key=lambda candidate: candidate["label"].casefold(),
                )
                options = [candidate["kind"] for candidate in palette]
                if not is_admin:
                    options = [kind for kind in options if kind != "custom"]
                selected = st.selectbox(
                    "Operation",
                    options=options,
                    index=None,
                    placeholder="Choose an operation",
                    format_func=lambda kind: _palette_entry(kind)["label"],
                    key=_key(state, "operation"),
                )
                if selected is not None:
                    selected_state = select_add_kind(state, selected)
                    state.selected_kind = selected_state.selected_kind
                    state.working_copy = selected_state.working_copy
                    state.discard_pending = False
                    # Rebuild the runtime dialog wrapper so its title names
                    # the newly selected operation.
                    st.rerun()
            elif state.working_copy is not None and _preview_required(
                current_operation, current_entry
            ):
                setup_column, preview_column = st.columns([5, 6])
                with setup_column:
                    _render_with_draft_restore(
                        state,
                        lambda: render_selected_operation(
                            state, is_admin=is_admin
                        ),
                    )
                with preview_column:
                    _render_with_draft_restore(
                        state,
                        lambda: _render_preview(
                            state, store=store, previews=previews
                        ),
                    )
            elif state.working_copy is not None:
                _render_with_draft_restore(
                    state,
                    lambda: render_selected_operation(
                        state, is_admin=is_admin
                    ),
                )

        if "Technical details" in tabs and state.working_copy is not None:
            with tabs["Technical details"]:
                _render_with_draft_restore(
                    state,
                    lambda: _render_technical(state.working_copy),
                )

        with tabs["Reference"]:
            _render_reference(current_entry, include_custom=is_admin)

        if st.button(
            "Keep in task",
            key=_key(state, "keep"),
            disabled=state.working_copy is None,
        ):
            on_keep(keep_in_task(operations, state))
            st.rerun()
        if st.button("Cancel", key=_key(state, "cancel")):
            if cancel_result(state) == "confirm":
                state.discard_pending = True
            else:
                on_close()
                st.rerun()
        if state.discard_pending:
            if st.button(
                "Discard changes", key=_key(state, "discard_changes")
            ):
                on_close()
                st.rerun()
            if st.button(
                "Keep editing", key=_key(state, "keep_editing")
            ):
                state.discard_pending = False
                rerun_fragment_or_app()

    wrapper = st.dialog(
        title,
        width="large",
        dismissible=False,
    )(render_function)
    wrapper()
