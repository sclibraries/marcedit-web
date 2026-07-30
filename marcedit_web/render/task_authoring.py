"""Streamlit controls for structured Add Field and Build Field operations."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Optional

import streamlit as st
from pymarc import Record

from marcedit_web.lib import task_authoring, task_builder


EXISTING_FIELD_OPTIONS = (
    ("append", "Add another field"),
    ("replace_all", "Replace every field with this tag"),
    ("skip_if_tag_exists", "Leave the record unchanged"),
    ("skip_if_identical", "Add unless an identical field already exists"),
)
MISSING_CONTROL_OPTIONS = (
    ("skip_field", "Do not build this field"),
    ("fail_record", "Record a task error for this record"),
)
SEGMENT_TYPE_OPTIONS = (
    ("text", "Literal text"),
    ("control_field", "Source control field"),
)


def _key(prefix: str, *parts: object) -> str:
    return "_".join([prefix] + [str(part) for part in parts])


def _select_policy(
    label: str,
    current: str,
    options: tuple[tuple[str, str], ...],
    *,
    key: str,
) -> str:
    values = [value for value, _label in options]
    labels = dict(options)
    if current not in values:
        current = values[0]
    return st.selectbox(
        label,
        options=values,
        index=values.index(current),
        format_func=lambda value: labels[value],
        key=key,
    )


def _render_common_params(params: dict, *, key_prefix: str) -> None:
    tag_col, ind1_col, ind2_col = st.columns([2, 1, 1])
    params["tag"] = tag_col.text_input(
        "Tag",
        value=str(params.get("tag", "")),
        max_chars=3,
        key=_key(key_prefix, "tag"),
    )
    params["ind1"] = ind1_col.text_input(
        "Indicator 1",
        value=str(params.get("ind1", " "))[:1] or " ",
        max_chars=1,
        key=_key(key_prefix, "ind1"),
        help="Single character; space for blank.",
    )
    params["ind2"] = ind2_col.text_input(
        "Indicator 2",
        value=str(params.get("ind2", " "))[:1] or " ",
        max_chars=1,
        key=_key(key_prefix, "ind2"),
        help="Single character; space for blank.",
    )
    condition_values = list(task_builder.LEADER_CONDITIONS)
    current_condition = str(params.get("condition") or "always")
    if current_condition not in condition_values:
        current_condition = "always"
    params["condition"] = st.selectbox(
        "Apply when",
        options=condition_values,
        index=condition_values.index(current_condition),
        format_func=lambda value: task_builder.LEADER_CONDITION_LABELS[value],
        key=_key(key_prefix, "condition"),
    )
    params["existing_field_action"] = _select_policy(
        "When this tag already exists",
        str(params.get("existing_field_action") or "append"),
        EXISTING_FIELD_OPTIONS,
        key=_key(key_prefix, "existing_field_action"),
    )


def _move_or_remove(
    items: list,
    index: int,
    *,
    key_prefix: str,
) -> tuple[list, bool]:
    controls = st.columns(3)
    if controls[0].button(
        "↑",
        key=_key(key_prefix, index, "up"),
        disabled=index == 0,
    ):
        return task_authoring.move_item(items, index, -1), True
    if controls[1].button(
        "↓",
        key=_key(key_prefix, index, "down"),
        disabled=index == len(items) - 1,
    ):
        return task_authoring.move_item(items, index, 1), True
    if controls[2].button(
        "Remove",
        key=_key(key_prefix, index, "remove"),
    ):
        return items[:index] + items[index + 1 :], True
    return items, False


def render_add_field_params(params: dict, *, key_prefix: str) -> None:
    """Render one complete row-based Add Field card."""

    _render_common_params(params, key_prefix=key_prefix)
    rows = copy.deepcopy(list(params.get("subfields") or []))
    collected = []
    for index, row in enumerate(rows):
        code, value = row
        fields = st.columns([1, 5])
        code = fields[0].text_input(
            "Subfield code",
            value=str(code),
            max_chars=1,
            key=_key(key_prefix, "sf", index, "code"),
        )
        value = fields[1].text_input(
            "Subfield value",
            value=str(value),
            key=_key(key_prefix, "sf", index, "value"),
        )
        collected.append([code, value])
        child_prefix = _key(key_prefix, "sf", index)
        moved, changed = _move_or_remove(
            collected + rows[index + 1 :],
            index,
            key_prefix=child_prefix,
        )
        if changed:
            params["subfields"] = moved
            st.rerun()
            return
    params["subfields"] = collected
    if st.button("Add subfield", key=_key(key_prefix, "add_subfield")):
        params["subfields"].append(["", ""])
        st.rerun()


def _render_segment(
    segment: dict,
    *,
    key_prefix: str,
) -> dict:
    values = [value for value, _label in SEGMENT_TYPE_OPTIONS]
    labels = dict(SEGMENT_TYPE_OPTIONS)
    current = str(segment.get("type") or "text")
    if current not in values:
        current = "text"
    segment_type = st.selectbox(
        "Segment type",
        options=values,
        index=values.index(current),
        format_func=lambda value: labels[value],
        key=_key(key_prefix, "type"),
    )
    if segment_type == "control_field":
        return {
            "type": "control_field",
            "tag": st.text_input(
                "Source control field",
                value=(
                    str(segment.get("tag", ""))
                    if current == "control_field"
                    else ""
                ),
                max_chars=3,
                key=_key(key_prefix, "tag"),
            ),
        }
    return {
        "type": "text",
        "value": st.text_input(
            "Literal text",
            value=(
                str(segment.get("value", ""))
                if current == "text"
                else ""
            ),
            key=_key(key_prefix, "value"),
        ),
    }


def render_build_field_params(params: dict, *, key_prefix: str) -> None:
    """Render one complete typed-segment Build Field card."""

    _render_common_params(params, key_prefix=key_prefix)
    params["missing_control_action"] = _select_policy(
        "When a source control field is missing",
        str(params.get("missing_control_action") or "skip_field"),
        MISSING_CONTROL_OPTIONS,
        key=_key(key_prefix, "missing_control_action"),
    )
    rows = copy.deepcopy(list(params.get("structured_subfields") or []))
    collected_rows = []
    for subfield_index, row in enumerate(rows):
        code, segments = row
        subfield_prefix = _key(key_prefix, "sf", subfield_index)
        code = st.text_input(
            "Subfield code",
            value=str(code),
            max_chars=1,
            key=_key(subfield_prefix, "code"),
        )
        collected_segments = []
        for segment_index, segment in enumerate(segments):
            segment_prefix = _key(
                subfield_prefix, "seg", segment_index
            )
            collected_segments.append(
                _render_segment(segment, key_prefix=segment_prefix)
            )
            moved, changed = _move_or_remove(
                collected_segments + segments[segment_index + 1 :],
                segment_index,
                key_prefix=segment_prefix,
            )
            if changed:
                rows[subfield_index] = [code, moved]
                params["structured_subfields"] = rows
                st.rerun()
                return
        if st.button(
            "Add segment",
            key=_key(subfield_prefix, "add_segment"),
        ):
            collected_segments.append({"type": "text", "value": ""})
            rows[subfield_index] = [code, collected_segments]
            params["structured_subfields"] = rows
            st.rerun()
            return
        collected_rows.append([code, collected_segments])
        moved, changed = _move_or_remove(
            collected_rows + rows[subfield_index + 1 :],
            subfield_index,
            key_prefix=subfield_prefix,
        )
        if changed:
            params["structured_subfields"] = moved
            st.rerun()
            return
    params["structured_subfields"] = collected_rows
    if st.button("Add subfield", key=_key(key_prefix, "add_subfield")):
        params["structured_subfields"].append(
            ["", [{"type": "text", "value": ""}]]
        )
        st.rerun()


def render_operation_explanation(
    op: Mapping[str, Any],
    record: Optional[Record],
) -> None:
    """Render explanation, mnemonic, annotations, and first-record preview."""

    authoring_error = str(op.get("authoring_error") or "")
    validation_errors = task_authoring.validate_operation(op)
    if authoring_error or validation_errors:
        message = authoring_error or "; ".join(validation_errors)
        st.warning(message)
        st.code(task_authoring.render_mnemonic(op), language="text")
        return
    st.caption(task_authoring.describe_operation(op))
    st.code(task_authoring.render_mnemonic(op), language="text")
    with st.expander("What this MARC syntax means"):
        for annotation in task_authoring.token_annotations(op):
            st.markdown("- " + annotation)
    preview = task_authoring.preview_operation(op, record)
    if preview.status == "ready":
        st.code(preview.mnemonic, language="text")
    elif preview.status == "error":
        st.error(preview.message)
    else:
        st.info(preview.message)
