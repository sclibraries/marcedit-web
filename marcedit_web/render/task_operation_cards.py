"""Compact card views for structured task operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

import streamlit as st

from marcedit_web.lib import (
    guided_replace_preview,
    task_authoring,
    task_builder,
)


@dataclass(frozen=True)
class OperationCardView:
    position: int
    kind: str
    label: str
    summary: str
    target: str
    validation_status: str
    validation_errors: tuple[str, ...]
    preview_status: str


def _palette_entry(kind: str) -> Optional[Mapping[str, Any]]:
    return next(
        (
            entry
            for entry in task_builder.OPERATIONS_PALETTE
            if entry["kind"] == kind
        ),
        None,
    )


def _operation_summary(
    operation: Mapping[str, Any],
    entry: Optional[Mapping[str, Any]],
) -> str:
    if entry is None:
        return "Unsupported operation; technical values are preserved."
    kind = str(operation.get("kind") or "")
    try:
        if kind in {"add-field", "build-field"}:
            return task_authoring.describe_operation(operation)
        if kind == "guided-find-replace":
            return task_authoring.describe_guided_replace(operation)
    except (KeyError, TypeError, ValueError):
        pass
    return str(entry["summary"])


def _operation_target(operation: Mapping[str, Any]) -> str:
    params = operation.get("params") or {}
    if not isinstance(params, Mapping):
        return ""
    tag = params.get("tag")
    subfield = params.get("subfield")
    if tag and subfield:
        return "{0} ${1}".format(tag, subfield)
    if tag:
        return str(tag)
    if params.get("src_tag") and params.get("dst_tag"):
        return "{0} → {1}".format(params["src_tag"], params["dst_tag"])
    return ""


def _preview_status(
    operation: Mapping[str, Any],
    *,
    store,
    previews: Mapping[str, guided_replace_preview.GuidedReplacePreview],
) -> str:
    if operation.get("kind") != "guided-find-replace":
        return ""
    try:
        cache_key = guided_replace_preview.preview_cache_key(operation)
    except (TypeError, ValueError):
        return "Not previewed"
    preview = previews.get(cache_key)
    if preview is None:
        return "Not previewed"
    if preview.error is not None:
        return "Failed"
    if guided_replace_preview.is_current(preview, store, operation):
        return "Current"
    return "Stale"


def operation_card_view(
    operation: Mapping[str, Any],
    *,
    position: int,
    store,
    previews: Mapping[str, guided_replace_preview.GuidedReplacePreview],
) -> OperationCardView:
    """Return the compact, cataloger-facing state for one operation."""

    kind = str(operation.get("kind") or "")
    entry = _palette_entry(kind)
    validation_errors = task_authoring.validate_operation(
        operation,
        validate_raw_syntax=False,
    )
    return OperationCardView(
        position=position,
        kind=kind,
        label=str(entry["label"]) if entry is not None else kind,
        summary=_operation_summary(operation, entry),
        target=_operation_target(operation),
        validation_status=(
            "Needs attention" if validation_errors else "Valid"
        ),
        validation_errors=validation_errors,
        preview_status=_preview_status(
            operation,
            store=store,
            previews=previews,
        ),
    )


def move_operation(
    operations: Sequence[dict],
    index: int,
    delta: int,
) -> list[dict]:
    """Copy the operation list and apply one in-range move."""

    moved = list(operations)
    destination = index + delta
    if (
        index < 0
        or index >= len(moved)
        or destination < 0
        or destination >= len(moved)
    ):
        return moved
    moved[index], moved[destination] = moved[destination], moved[index]
    return moved


def remove_operation(
    operations: Sequence[dict],
    index: int,
) -> list[dict]:
    """Copy the operation list and remove one in-range operation."""

    copied = list(operations)
    if index < 0 or index >= len(copied):
        return copied
    return copied[:index] + copied[index + 1 :]


def _key(prefix: str, index: int, action: str) -> str:
    return "{0}_{1}_{2}".format(prefix, index, action)


def _validation_caption(view: OperationCardView) -> str:
    if not view.validation_errors:
        return view.validation_status
    if (
        len(view.validation_errors) == 1
        and len(view.validation_errors[0]) <= 160
    ):
        return "Needs attention — {0}".format(view.validation_errors[0])
    return "Needs attention — edit to review {0} issues".format(
        len(view.validation_errors)
    )


def render_operation_cards(
    operations: Sequence[dict],
    *,
    store,
    previews: Mapping[str, guided_replace_preview.GuidedReplacePreview],
    on_edit: Callable[[int], None],
    on_change: Callable[[list[dict]], None],
    key_prefix: str = "task_operation_cards",
) -> None:
    """Render compact cards and report edit, move, or remove actions."""

    pending_key = "{0}_pending_remove".format(key_prefix)
    for index, operation in enumerate(operations):
        view = operation_card_view(
            operation,
            position=index + 1,
            store=store,
            previews=previews,
        )
        with st.container(border=True):
            heading, target = st.columns([4, 1])
            heading.markdown(
                "**{0}. {1}**".format(view.position, view.label)
            )
            if view.target:
                target.caption("Target: {0}".format(view.target))

            summary, status = st.columns([4, 2])
            summary.caption(view.summary)
            status_text = _validation_caption(view)
            if view.preview_status:
                status_text = "{0} · {1}".format(
                    status_text, view.preview_status
                )
            status.caption(status_text)

            actions = st.columns(4)
            edit_clicked = actions[0].button(
                "Edit",
                key=_key(key_prefix, index, "edit"),
            )
            up_clicked = actions[1].button(
                "↑",
                key=_key(key_prefix, index, "up"),
                disabled=index == 0,
                help="Move operation up",
            )
            down_clicked = actions[2].button(
                "↓",
                key=_key(key_prefix, index, "down"),
                disabled=index == len(operations) - 1,
                help="Move operation down",
            )

            if st.session_state.get(pending_key) == index:
                remove_clicked = actions[3].button(
                    "Confirm removal",
                    key=_key(key_prefix, index, "confirm_remove"),
                )
                confirming_remove = True
            else:
                remove_clicked = actions[3].button(
                    "Remove",
                    key=_key(key_prefix, index, "remove"),
                )
                confirming_remove = False

            if edit_clicked:
                on_edit(index)
                return
            if up_clicked:
                st.session_state.pop(pending_key, None)
                on_change(move_operation(operations, index, -1))
                return
            if down_clicked:
                st.session_state.pop(pending_key, None)
                on_change(move_operation(operations, index, 1))
                return
            if remove_clicked and confirming_remove:
                st.session_state.pop(pending_key, None)
                on_change(remove_operation(operations, index))
                return
            if remove_clicked:
                st.session_state[pending_key] = index
