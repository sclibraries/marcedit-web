"""Streamlit controls for structured Add Field and Build Field operations."""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping, Optional

import streamlit as st
from pymarc import Record

from marcedit_web.lib import (
    guided_replace_preview,
    task_authoring,
    task_builder,
)


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
GUIDED_TARGET_OPTIONS = (
    ("subfield", "One subfield code"),
    ("all_subfields", "All subfield values in a tag"),
    ("control_field", "A control field value"),
)
GUIDED_MATCH_OPTIONS = (
    ("contains", "Contains"),
    ("starts_with", "Starts with"),
    ("ends_with", "Ends with"),
    ("whole_value", "Is the whole value"),
)
GUIDED_REPLACEMENT_OPTIONS = (
    ("matched_text", "Replace the matched text"),
    ("whole_value", "Replace the whole selected value"),
    ("prepend", "prepend"),
    ("append", "append"),
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


def render_guided_find_replace_params(
    params: dict,
    *,
    key_prefix: str,
) -> None:
    """Render progressive controls for one guided value replacement."""

    replacement_mode_key = _key(key_prefix, "replacement_mode")
    advanced_key = _key(key_prefix, "advanced_regex")
    preserved_key = _key(key_prefix, "preserved_raw_find")
    pending_key = _key(key_prefix, "pending_mode_switch")
    pending = st.session_state.pop(pending_key, None)
    if isinstance(pending, Mapping):
        if pending.get("action") == "keep":
            st.session_state[advanced_key] = True
            st.session_state[replacement_mode_key] = pending[
                "previous_replacement_mode"
            ]
        elif pending.get("action") == "discard":
            requested_mode = pending["requested_replacement_mode"]
            params["replacement_mode"] = requested_mode
            params["match_mode"] = (
                "none"
                if requested_mode in {"prepend", "append"}
                else "contains"
            )
            params["find"] = ""
            if requested_mode in {"prepend", "append"}:
                params["occurrences"] = "all"
                st.session_state.pop(advanced_key, None)
            else:
                st.session_state[advanced_key] = False
            st.session_state[replacement_mode_key] = requested_mode
        st.session_state.pop(preserved_key, None)

    previous_target_kind = str(params.get("target_kind") or "subfield")
    params["target_kind"] = _select_policy(
        "Where should Smith Metadata Studio look?",
        previous_target_kind,
        GUIDED_TARGET_OPTIONS,
        key=_key(key_prefix, "target_kind"),
    )
    if (
        params["target_kind"] != previous_target_kind
        and params["target_kind"] != "subfield"
    ):
        params["subfield"] = ""
    params["tag"] = st.text_input(
        "Tag",
        value=str(params.get("tag", "")),
        max_chars=3,
        key=_key(key_prefix, "tag"),
    )
    if params["target_kind"] == "subfield":
        params["subfield"] = st.text_input(
            "Subfield code",
            value=str(params.get("subfield", "")),
            max_chars=1,
            key=_key(key_prefix, "subfield"),
        )

    previous_replacement_mode = str(
        params.get("replacement_mode") or "matched_text"
    )
    requested_replacement_mode = _select_policy(
        "What should it change?",
        previous_replacement_mode,
        GUIDED_REPLACEMENT_OPTIONS,
        key=replacement_mode_key,
    )
    previous_match_mode = str(params.get("match_mode") or "contains")
    requested_raw = False
    if requested_replacement_mode not in {"prepend", "append"}:
        requested_raw = st.checkbox(
            "Write a regular expression directly",
            value=previous_match_mode == "raw_regex",
            key=advanced_key,
        )

    leaving_raw = (
        previous_match_mode == "raw_regex"
        and (
            not requested_raw
            or requested_replacement_mode in {"prepend", "append"}
        )
    )
    if leaving_raw:
        st.session_state[preserved_key] = params.get("find", "")
        st.warning(
            "Switching modes will discard the current regular expression."
        )
        if st.button(
            "Keep current mode",
            key=_key(key_prefix, "mode_switch_keep"),
        ):
            st.session_state[pending_key] = {
                "action": "keep",
                "previous_replacement_mode": previous_replacement_mode,
            }
        if st.button(
            "Discard matching text and switch",
            key=_key(key_prefix, "mode_switch_discard"),
        ):
            st.session_state[pending_key] = {
                "action": "discard",
                "requested_replacement_mode": requested_replacement_mode,
            }
        return

    params["replacement_mode"] = requested_replacement_mode
    if requested_replacement_mode in {"prepend", "append"}:
        params["match_mode"] = "none"
        params["find"] = ""
        params["occurrences"] = "all"
    elif requested_raw:
        params["match_mode"] = "raw_regex"
        params["find"] = st.text_input(
            "Find regular expression",
            value=str(params.get("find", "")),
            key=_key(key_prefix, "find_regex"),
        )
    else:
        params["match_mode"] = _select_policy(
            "How should it match?",
            (
                previous_match_mode
                if previous_match_mode != "raw_regex"
                else "contains"
            ),
            GUIDED_MATCH_OPTIONS,
            key=_key(key_prefix, "match_mode"),
        )
        params["find"] = st.text_input(
            "Find",
            value=str(params.get("find", "")),
            key=_key(key_prefix, "find"),
        )

    if requested_replacement_mode not in {"prepend", "append"}:
        params["ignore_case"] = st.checkbox(
            "Ignore uppercase/lowercase differences",
            value=bool(params.get("ignore_case", False)),
            key=_key(key_prefix, "ignore_case"),
        )
    params["replacement"] = st.text_input(
        "Replace with",
        value=str(params.get("replacement", "")),
        key=_key(key_prefix, "replacement"),
    )

    if (
        params["replacement_mode"] == "matched_text"
        and params["match_mode"] in {"contains", "raw_regex"}
    ):
        occurrence_values = ("first", "all")
        current_occurrences = str(params.get("occurrences") or "all")
        if current_occurrences not in occurrence_values:
            current_occurrences = "all"
        params["occurrences"] = st.radio(
            "First or every match?",
            options=occurrence_values,
            index=occurrence_values.index(current_occurrences),
            format_func=lambda value: {
                "first": "First",
                "all": "Every",
            }[value],
            horizontal=True,
            key=_key(key_prefix, "occurrences"),
        )
    elif params["replacement_mode"] in {"prepend", "append"}:
        params["occurrences"] = "all"
    else:
        params["occurrences"] = "first"

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


def guided_replace_previewed_discard_count(
    operation: Mapping[str, Any],
    store,
    previews: Mapping[str, guided_replace_preview.GuidedReplacePreview],
) -> int:
    """Return the whole-value discard count from a current preview."""

    if (
        store is None
        or operation.get("params", {}).get("replacement_mode")
        != "whole_value"
    ):
        return 0
    try:
        cache_key = guided_replace_preview.preview_cache_key(operation)
    except (TypeError, ValueError):
        return 0
    preview = previews.get(cache_key)
    if (
        preview is None
        or not guided_replace_preview.is_current(preview, store, operation)
    ):
        return 0
    return int((preview.result or {}).get("matched_values", 0))


def _guided_match_pattern(params: Mapping[str, Any]) -> str:
    match_mode = params["match_mode"]
    if match_mode == "none":
        return "(none; prepend and append do not match text)"
    if match_mode == "raw_regex":
        return str(params["find"])
    pattern = re.escape(str(params["find"]))
    if match_mode == "starts_with":
        return "^" + pattern
    if match_mode == "ends_with":
        return pattern + "$"
    if match_mode == "whole_value":
        return "^" + pattern + "$"
    return pattern


def render_guided_replace_technical_details(
    operation: Mapping[str, Any],
) -> None:
    """Show saved guided choices and their generated matching behavior."""

    params = task_authoring.normalize_guided_replace_operation(
        operation
    )["params"]
    saved_choices = "\n".join(
        "{0}={1}".format(name, params[name])
        for name in (
            "target_kind",
            "tag",
            "subfield",
            "match_mode",
            "find",
            "ignore_case",
            "replacement_mode",
            "replacement",
            "occurrences",
            "condition",
        )
    )
    case_behavior = (
        "case-insensitive"
        if params["ignore_case"]
        else "case-sensitive"
    )
    technical = (
        "Saved choices:\n{0}\n\n"
        "Generated match pattern: {1}\n"
        "Case handling: {2}\n"
        "Replacement behavior: {3}; occurrences={4}"
    ).format(
        saved_choices,
        _guided_match_pattern(params),
        case_behavior,
        params["replacement_mode"],
        params["occurrences"],
    )
    with st.expander("Technical matching details"):
        st.code(technical, language="text")
        st.markdown(
            "[Open the task authoring syntax reference]"
            "(https://github.com/sclibraries/marcedit-web/blob/main/"
            "docs/task-authoring-syntax.md)"
        )


def render_guided_replace_preview(
    operation: Mapping[str, Any],
    store,
    previews: dict,
    *,
    key_prefix: str,
) -> int:
    """Render one request-keyed preview without running it on rerenders."""

    try:
        cache_key = guided_replace_preview.preview_cache_key(operation)
    except (TypeError, ValueError) as exc:
        st.error("Preview validation failed: {0}".format(exc))
        return 0

    if st.button(
        "Preview this operation",
        key=_key(key_prefix, "preview"),
    ):
        if store is None:
            normalized = task_authoring.normalize_operation(operation)
            previews[cache_key] = (
                guided_replace_preview.GuidedReplacePreview(
                    request=normalized["params"],
                    store_id=None,
                    store_revision=None,
                    error="No loaded file is available to preview.",
                )
            )
        else:
            previews[cache_key] = guided_replace_preview.build_preview(
                store, operation
            )

    preview = previews.get(cache_key)
    if preview is None:
        st.info(
            "Preview this operation against the first loaded record "
            "before running it."
        )
        return 0
    if preview.error is not None:
        st.error(preview.error)
        return 0

    result = preview.result or {}
    matched_values = int(result.get("matched_values", 0))
    changed_values = int(result.get("changed_values", 0))
    matched_occurrences = int(result.get("matched_occurrences", 0))
    st.caption(
        "Matched values: {0} · Changed values: {1} · "
        "Matched occurrences: {2}".format(
            matched_values,
            changed_values,
            matched_occurrences,
        )
    )
    if matched_values == 0:
        st.info("Preview found zero matches in the first loaded record.")
    discard_count = guided_replace_previewed_discard_count(
        operation, store, previews
    )
    if discard_count:
        st.warning(
            "This operation will replace {0} whole selected value(s) "
            "in the preview record.".format(discard_count)
        )
    st.markdown("**Before**")
    st.code(preview.before or "(no selected values)", language="text")
    st.markdown("**After**")
    st.code(preview.after or "(no selected values)", language="text")
    return discard_count


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
