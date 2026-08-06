"""Streamlit renderer for the focused Common field changes workflow.

The renderer is intentionally a thin UI boundary.  It constructs one
``QuickFieldChangeRequest`` from explicit widgets and delegates execution to
the sandbox-backed runner; no MARC records or regular expressions are
processed in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

import streamlit as st

from marcedit_web.lib import quick_field_change_runner, quick_field_changes
from marcedit_web.lib.quick_field_changes import QuickFieldChangeRequest
from marcedit_web.lib.quick_field_selector import (
    FieldFilter,
    FieldSelector,
    IndicatorFilter,
    Occurrence,
)
from marcedit_web.lib import transforms


KEY_PREFIX = "quick_field_change_"
K_OPERATION = KEY_PREFIX + "operation"
K_PREVIEW = KEY_PREFIX + "preview"
K_RESET = KEY_PREFIX + "reset"
K_PREVIEW_BUTTON = KEY_PREFIX + "preview"
K_APPLY_BUTTON = KEY_PREFIX + "apply"

EXPECTED_LABELS = [
    "Add field",
    "Add subfield",
    "Copy field",
    "Delete field",
    "Delete subfield",
    "Move or retag field",
    "Remove exact duplicate fields",
    "Set indicators",
    "Swap field occurrences",
]
# Public aliases keep the renderer contract discoverable to callers/tests
# without making the UI depend on internal dictionary names.
OPERATION_LABELS = EXPECTED_LABELS

OPERATION_KINDS: Mapping[str, str] = {
    "Add field": "add-field",
    "Add subfield": "add-subfield",
    "Copy field": "copy-field",
    "Delete field": "delete-field",
    "Delete subfield": "delete-subfield",
    "Move or retag field": "move-field",
    "Remove exact duplicate fields": "remove-duplicate-fields",
    "Set indicators": "set-indicators",
    "Swap field occurrences": "swap-field-occurrences",
}

# The operation matrix is deliberately data, rather than a set of conditionals
# spread across the form.  ``every`` is not legal for Swap and the two
# collection-wide operations do not have an occurrence selector at all.
OCCURRENCE_COMPATIBILITY: Mapping[str, tuple[str, ...]] = {
    "add-field": (),
    "add-subfield": ("first", "last", "every", "numbered"),
    "copy-field": ("first", "last", "every", "numbered"),
    "delete-field": ("first", "last", "every", "numbered"),
    "delete-subfield": ("first", "last", "every", "numbered"),
    "move-field": ("first", "last", "every", "numbered"),
    "remove-duplicate-fields": (),
    "set-indicators": ("first", "last", "every", "numbered"),
    "swap-field-occurrences": ("first", "last", "numbered"),
}
COMPATIBILITY_MATRIX = OCCURRENCE_COMPATIBILITY

_OCCURRENCE_LABELS = {
    "first": "First matching field",
    "last": "Last matching field",
    "every": "Every matching field",
    "numbered": "Numbered matching field",
}
_OCCURRENCE_FROM_LABEL = {value: key for key, value in _OCCURRENCE_LABELS.items()}
_MATCH_MODE_LABELS = {
    "exact": "Exact",
    "contains": "Contains",
    "starts_with": "Starts with",
    "ends_with": "Ends with",
}
_MATCH_MODE_FROM_LABEL = {value: key for key, value in _MATCH_MODE_LABELS.items()}
_INDICATOR_FILTER_LABELS = ("Any", "MARC blank", "Exact value")
_INDICATOR_FILTER_FROM_LABEL = {
    "Any": IndicatorFilter(),
    "MARC blank": IndicatorFilter(mode="blank"),
}


@dataclass(frozen=True)
class _SelectorControls:
    selector: FieldSelector
    is_control: bool


def _widget_key(suffix: str) -> str:
    return KEY_PREFIX + suffix


def _text(label: str, *, key: str, value: str = "", **kwargs) -> str:
    return str(st.text_input(label, value=value, key=key, **kwargs) or "")


def _choice(label: str, options: Iterable[str], *, key: str, index: int = 0) -> str:
    values = list(options)
    if not values:
        return ""
    index = max(0, min(index, len(values) - 1))
    return str(st.selectbox(label, options=values, index=index, key=key))


def _checkbox(label: str, *, key: str, value: bool = False, **kwargs) -> bool:
    return bool(st.checkbox(label, value=value, key=key, **kwargs))


def _is_control_tag(tag: str) -> bool:
    return transforms.is_control_tag(tag)


def _indicator_filter(label: str, *, key: str) -> IndicatorFilter:
    mode_label = _choice(label, _INDICATOR_FILTER_LABELS, key=key)
    if mode_label == "Exact value":
        value = _text(
            f"{label} exact character",
            key=key + "_value",
            max_chars=1,
        )
        return IndicatorFilter(mode="exact", value=value[:1])
    return _INDICATOR_FILTER_FROM_LABEL[mode_label]


def _match_controls(prefix: str, *, allow_subfield: bool) -> tuple[str, str, str, bool]:
    """Render guided matching and return code/mode/value/case values.

    Raw regex is an opt-in widget inside a collapsed advanced section.  It only
    changes the immutable ``FieldFilter`` value; compilation occurs in the
    sandbox selector boundary.
    """

    subfield_code = ""
    if allow_subfield:
        subfield_code = _text(
            "Subfield code",
            key=_widget_key(prefix + "_subfield_code"),
            max_chars=1,
        ).strip().lower()
    match_mode = "exact"
    match_value = ""
    ignore_case = False
    if allow_subfield and subfield_code:
        match_mode_label = _choice(
            "Match mode",
            tuple(_MATCH_MODE_LABELS.values()),
            key=_widget_key(prefix + "_match_mode"),
        )
        match_mode = _MATCH_MODE_FROM_LABEL[match_mode_label]
        match_value = _text(
            "Match value",
            key=_widget_key(prefix + "_match_value"),
        )
        ignore_case = _checkbox(
            "Ignore case",
            key=_widget_key(prefix + "_ignore_case"),
        )
        with st.expander("Advanced: regular expression", expanded=False):
            if _checkbox(
                "Use raw regular expression",
                key=_widget_key(prefix + "_raw_regex"),
            ):
                match_mode = "raw_regex"
    return subfield_code, match_mode, match_value, ignore_case


def _render_selector(
    prefix: str,
    *,
    occurrence_choices: tuple[str, ...],
    allow_occurrence: bool = True,
    allow_indicators: bool = True,
    allow_subfield: bool = True,
    tag_label: str = "Field tag",
) -> _SelectorControls:
    tag = _text(tag_label, key=_widget_key(prefix + "_tag"), max_chars=3).strip().upper()
    is_control = _is_control_tag(tag)
    ind1 = IndicatorFilter()
    ind2 = IndicatorFilter()
    if allow_indicators and not is_control:
        ind1 = _indicator_filter(
            "Indicator 1 filter",
            key=_widget_key(prefix + "_ind1_filter"),
        )
        ind2 = _indicator_filter(
            "Indicator 2 filter",
            key=_widget_key(prefix + "_ind2_filter"),
        )
    subfield_code, match_mode, match_value, ignore_case = _match_controls(
        prefix,
        allow_subfield=allow_subfield and not is_control,
    )
    occurrence = Occurrence()
    if allow_occurrence and occurrence_choices:
        labels = tuple(_OCCURRENCE_LABELS[value] for value in occurrence_choices)
        occurrence_label = _choice(
            "Occurrence",
            labels,
            key=_widget_key(prefix + "_occurrence"),
        )
        occurrence_mode = _OCCURRENCE_FROM_LABEL[occurrence_label]
        number = None
        if occurrence_mode == "numbered":
            raw_number = st.number_input(
                "Occurrence number",
                min_value=1,
                max_value=999,
                value=1,
                step=1,
                key=_widget_key(prefix + "_occurrence_number"),
            )
            try:
                number = int(raw_number)
            except (TypeError, ValueError):
                number = 1
            number = max(1, min(number, 999))
        occurrence = Occurrence(mode=occurrence_mode, number=number)
    selector = FieldSelector(
        FieldFilter(
            tag=tag,
            ind1=ind1,
            ind2=ind2,
            subfield_code=subfield_code,
            match_mode=match_mode,
            match_value=match_value,
            ignore_case=ignore_case,
        ),
        occurrence=occurrence,
    )
    return _SelectorControls(selector=selector, is_control=is_control)


def _render_subfields(prefix: str) -> tuple[tuple[str, str], ...]:
    count_key = _widget_key(prefix + "_count")
    count = st.session_state.get(count_key, 1)
    try:
        count = max(1, min(int(count), 100))
    except (TypeError, ValueError):
        count = 1
    if st.button("Add another subfield", key=_widget_key(prefix + "_add_row")):
        count = min(100, count + 1)
        st.session_state[count_key] = count
    rows: list[tuple[str, str]] = []
    for index in range(count):
        suffix = "" if index == 0 else f" {index + 1}"
        code = _text(
            f"Subfield code{suffix}",
            key=_widget_key(f"{prefix}_code_{index}"),
            max_chars=1,
        )
        value = _text(
            f"Subfield value{suffix}",
            key=_widget_key(f"{prefix}_value_{index}"),
        )
        if code:
            rows.append((code.strip().lower(), value))
    return tuple(rows)


def _set_indicator_value(label: str, *, key: str) -> str | None:
    choice = _choice(
        label,
        ("Leave unchanged", "MARC blank", "Exact value"),
        key=key,
    )
    if choice == "Leave unchanged":
        return None
    if choice == "MARC blank":
        return " "
    return _text(
        f"{label} exact character",
        key=key + "_value",
        max_chars=1,
    )[:1]


def _render_add_field() -> QuickFieldChangeRequest:
    destination_tag = _text(
        "Destination tag",
        key=_widget_key("add_destination_tag"),
        max_chars=3,
    ).strip().upper()
    if _is_control_tag(destination_tag):
        control_value = _text(
            "Control field value",
            key=_widget_key("add_control_value"),
        )
        indicators = (None, None)
        subfields: tuple[tuple[str, str], ...] = ()
    else:
        ind1 = _text("Indicator 1", key=_widget_key("add_ind1"), max_chars=1)
        ind2 = _text("Indicator 2", key=_widget_key("add_ind2"), max_chars=1)
        subfields = _render_subfields("add_subfield")
        control_value = ""
        indicators = (ind1[:1], ind2[:1])
    scope = _choice(
        "Add field record scope",
        (
            "Every record",
            "Only when tag is absent",
            "Only when identical field is absent",
        ),
        key=_widget_key("add_record_scope"),
    )
    scope_value = {
        "Every record": "every",
        "Only when tag is absent": "tag_absent",
        "Only when identical field is absent": "identical_absent",
    }[scope]
    return QuickFieldChangeRequest(
        kind="add-field",
        destination_tag=destination_tag,
        control_value=control_value,
        ind1=indicators[0],
        ind2=indicators[1],
        subfields=subfields,
        record_scope=scope_value,
    )


def _render_selector_request(kind: str) -> tuple[QuickFieldChangeRequest, _SelectorControls]:
    controls = _render_selector(
        "primary",
        occurrence_choices=OCCURRENCE_COMPATIBILITY[kind],
    )
    return QuickFieldChangeRequest(kind=kind, selector=controls.selector), (controls,)


def _render_request(kind: str) -> tuple[QuickFieldChangeRequest, tuple[_SelectorControls, ...]]:
    if kind == "add-field":
        return _render_add_field(), ()
    if kind == "remove-duplicate-fields":
        controls = _render_selector(
            "duplicate",
            occurrence_choices=(),
            allow_occurrence=False,
        )
        keep = _choice(
            "Keep duplicate",
            ("First duplicate", "Last duplicate"),
            key=_widget_key("keep_duplicate"),
        )
        return QuickFieldChangeRequest(
            kind=kind,
            duplicate_filter=controls.selector.field_filter,
            keep_duplicate="first" if keep == "First duplicate" else "last",
        ), (controls,)
    if kind == "swap-field-occurrences":
        first = _render_selector(
            "first",
            occurrence_choices=OCCURRENCE_COMPATIBILITY[kind],
            tag_label="First field tag",
        )
        second = _render_selector(
            "second",
            occurrence_choices=OCCURRENCE_COMPATIBILITY[kind],
            tag_label="Second field tag",
        )
        return QuickFieldChangeRequest(
            kind=kind,
            selector=first.selector,
            second_selector=second.selector,
        ), (first, second)

    request, controls = _render_selector_request(kind)
    kwargs: dict[str, object] = {}
    if kind in {"copy-field", "move-field"}:
        kwargs["destination_tag"] = _text(
            "Destination tag",
            key=_widget_key(kind + "_destination_tag"),
            max_chars=3,
        ).strip().upper()
    if kind == "copy-field":
        policy = _choice(
            "Destination policy",
            (
                "Append",
                "Skip identical fields",
                "Replace all destination fields",
            ),
            key=_widget_key("copy_destination_policy"),
        )
        kwargs["destination_policy"] = {
            "Append": "append",
            "Skip identical fields": "skip_identical",
            "Replace all destination fields": "replace_all",
        }[policy]
    if kind == "add-subfield":
        kwargs["subfield_code"] = _text(
            "Subfield code",
            key=_widget_key("add_subfield_code"),
            max_chars=1,
        ).strip().lower()
        kwargs["subfield_value"] = _text(
            "Subfield value",
            key=_widget_key("add_subfield_value"),
        )
        kwargs["position"] = {
            "Append": "append",
            "Prepend": "prepend",
        }[_choice(
            "Subfield position",
            ("Append", "Prepend"),
            key=_widget_key("add_subfield_position"),
        )]
        kwargs["repeat_policy"] = {
            "Always add": "append",
            "Skip identical subfield": "skip_identical",
        }[_choice(
            "Repeat policy",
            ("Always add", "Skip identical subfield"),
            key=_widget_key("add_subfield_repeat_policy"),
        )]
    elif kind == "delete-subfield":
        kwargs["subfield_code"] = _text(
            "Subfield code",
            key=_widget_key("delete_subfield_code"),
            max_chars=1,
        ).strip().lower()
        kwargs["subfield_value"] = _text(
            "Subfield value match",
            key=_widget_key("delete_subfield_value"),
        )
        kwargs["subfield_occurrence"] = {
            "First matching subfield": "first",
            "Every matching subfield": "every",
        }[_choice(
            "Subfield occurrence",
            ("First matching subfield", "Every matching subfield"),
            key=_widget_key("delete_subfield_occurrence"),
        )]
        kwargs["remove_empty_field"] = _checkbox(
            "Remove field when empty",
            key=_widget_key("delete_subfield_remove_empty"),
        )
    elif kind == "set-indicators":
        if controls[0].is_control:
            st.info("Control fields do not have indicators to set.")
        else:
            kwargs["ind1"] = _set_indicator_value(
                "Set indicator 1",
                key=_widget_key("set_ind1"),
            )
            kwargs["ind2"] = _set_indicator_value(
                "Set indicator 2",
                key=_widget_key("set_ind2"),
            )
    return QuickFieldChangeRequest(kind=kind, selector=request.selector, **kwargs), controls


def _summary(request: QuickFieldChangeRequest) -> str:
    label = next(
        (name for name, kind in OPERATION_KINDS.items() if kind == request.kind),
        request.kind,
    )
    if request.kind == "add-field":
        return f"{label}: add {request.destination_tag or '(enter a tag)'} to the selected records."
    if request.kind == "remove-duplicate-fields":
        return f"{label}: keep the {request.keep_duplicate} exact copy for each matching tag."
    if request.selector is not None:
        tag = request.selector.field_filter.tag or "(enter a tag)"
        occurrence = _OCCURRENCE_LABELS.get(request.selector.occurrence.mode, "First matching field")
        if request.kind == "swap-field-occurrences" and request.second_selector is not None:
            second_tag = request.second_selector.field_filter.tag or "(enter a tag)"
            return (
                f"{label}: swap the {occurrence.lower()} {tag} with the "
                f"{_OCCURRENCE_LABELS.get(request.second_selector.occurrence.mode, 'first matching field').lower()} {second_tag}."
            )
        return f"{label}: {occurrence.lower()} for {tag}."
    return label


def _request_is_current(preview, request: QuickFieldChangeRequest, store, *, job_file_id, job_file_version_id) -> bool:
    if preview is None or preview.error is not None:
        return False
    if preview.store_id != id(store) or preview.store_revision != getattr(store, "revision", None):
        return False
    if preview.job_file_id != job_file_id or preview.job_file_version_id != job_file_version_id:
        return False
    try:
        return quick_field_changes.request_to_payload(preview.request) == quick_field_changes.request_to_payload(request)
    except Exception:
        return preview.request == request


def _render_preview_evidence(preview) -> None:
    columns = st.columns(6)
    metrics = (
        ("Records", preview.record_count),
        ("Changed", preview.changed_count),
        ("Unchanged", preview.unchanged_count),
        ("Skipped", preview.skipped_count),
        ("Fields affected", preview.fields_affected),
        ("Subfields affected", preview.subfields_affected),
    )
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)
    summary = preview.diff_summary
    if summary is not None:
        tags = sorted(
            set(summary.per_tag_added)
            | set(summary.per_tag_deleted)
            | set(summary.per_tag_modified)
        )
        for tag in tags:
            st.caption(
                f"{tag}: +{summary.per_tag_added.get(tag, 0)} "
                f"−{summary.per_tag_deleted.get(tag, 0)} "
                f"~{summary.per_tag_modified.get(tag, 0)}"
            )
    if preview.reason_counts:
        st.markdown("**Skip reasons**")
        for reason, count in sorted(preview.reason_counts.items())[:20]:
            if reason == "swap-same-field":
                st.warning(
                    f"{count} record(s) resolved both Swap selectors to the same field; "
                    "change one selector before applying."
                )
            st.caption(f"{reason}: {count}")
    if summary is None:
        return
    if summary.cap_triggered:
        st.caption("Representative record diffs are shown; the list is capped.")
    for item in summary.per_record_diffs:
        identifier = item.identifier or f"record {item.record_index + 1}"
        with st.expander(f"Record {identifier} changes", expanded=False):
            for before, after, status in item.rows:
                st.code(f"{status}:\n- {before}\n+ {after}", language="text")


def _clear_state() -> None:
    preview = st.session_state.get(K_PREVIEW)
    quick_field_change_runner.cleanup_artifact(preview)
    for key in list(st.session_state):
        if str(key).startswith(KEY_PREFIX):
            st.session_state.pop(key, None)


def render_common_field_changes(
    store,
    *,
    job_file_id: int | None = None,
    job_file_version_id: int | None = None,
    on_apply: Callable[[object, QuickFieldChangeRequest], object],
) -> None:
    """Render one preview-first Common field change operation."""

    if st.button("Reset", key=K_RESET):
        _clear_state()
        return

    selected_label = _choice("Operation", EXPECTED_LABELS, key=K_OPERATION)
    kind = OPERATION_KINDS[selected_label]
    request, controls = _render_request(kind)
    st.caption(_summary(request))

    if any(control.selector.occurrence.mode == "every" for control in controls):
        st.warning("Every-match may change multiple fields (a multi-field change) in one record.")

    if st.button("Preview", key=K_PREVIEW_BUTTON, disabled=store is None):
        previous = st.session_state.get(K_PREVIEW)
        quick_field_change_runner.cleanup_artifact(previous)
        if store is None:
            preview = quick_field_change_runner.QuickFieldChangePreview(
                request=request,
                request_json="",
                job_file_id=job_file_id,
                job_file_version_id=job_file_version_id,
                error="No loaded file is available to preview.",
            )
        else:
            preview = quick_field_change_runner.build_preview(
                store,
                request,
                job_file_id=job_file_id,
                job_file_version_id=job_file_version_id,
            )
        st.session_state[K_PREVIEW] = preview

    preview = st.session_state.get(K_PREVIEW)
    current = _request_is_current(
        preview,
        request,
        store,
        job_file_id=job_file_id,
        job_file_version_id=job_file_version_id,
    )
    if preview is not None and preview.error is not None:
        st.error(preview.error)
    elif preview is not None and not current:
        st.info("This preview is stale. Preview the current request again before applying.")
    elif preview is not None:
        _render_preview_evidence(preview)

    if st.button("Apply preview", key=K_APPLY_BUTTON, disabled=not current):
        on_apply(preview, request)


__all__ = [
    "EXPECTED_LABELS",
    "OPERATION_KINDS",
    "OCCURRENCE_COMPATIBILITY",
    "render_common_field_changes",
]
