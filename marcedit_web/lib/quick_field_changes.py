"""Pure one-record mutations used by focused Quick field changes.

The request values in this module are immutable and contain no MARC content
from a record.  Validation is deliberately performed before a mutation is
started; the fixed sandbox adapter can therefore call the same entry point as
the in-process preview tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import re
from typing import Any

from pymarc import Field, Record, Subfield

from . import transforms
from .quick_field_selector import (
    FieldFilter,
    FieldSelector,
    IndicatorFilter,
    Occurrence,
    matching_fields,
    resolve_fields,
    validate_field_filter,
    validate_selector,
)


_KINDS = frozenset(
    {
        "add-field",
        "add-subfield",
        "copy-field",
        "delete-field",
        "delete-subfield",
        "move-field",
        "remove-duplicate-fields",
        "set-indicators",
        "swap-field-occurrences",
    }
)
_ADD_SUBFIELD_KINDS = frozenset({"add-subfield"})
_DELETE_SUBFIELD_KINDS = frozenset({"delete-subfield"})
_COPY_KINDS = frozenset({"copy-field"})
_MOVE_KINDS = frozenset({"move-field"})
_DELETE_KINDS = frozenset({"delete-field"})
_DUPLICATE_KINDS = frozenset({"remove-duplicate-fields"})
_SET_INDICATOR_KINDS = frozenset({"set-indicators"})
_SWAP_KINDS = frozenset({"swap-field-occurrences"})
_POSITIONS = frozenset({"append", "prepend", "end", "start"})
_REPEAT_POLICIES = frozenset(
    {"append", "skip", "skip_identical", "skip-if-identical", "skip_if_identical"}
)
_RECORD_SCOPES = frozenset(
    {
        "every",
        "tag_absent",
        "when_tag_absent",
        "if_tag_absent",
        "identical_absent",
        "when_identical_absent",
        "if_identical_absent",
    }
)
_DESTINATION_POLICIES = frozenset(
    {"append", "skip", "skip_identical", "skip-if-identical", "replace_all", "replace-all"}
)
_SUBFIELD_OCCURRENCES = frozenset({"first", "every"})
_KEEP_DUPLICATES = frozenset({"first", "last"})


@dataclass(frozen=True)
class QuickFieldChangeRequest:
    kind: str
    selector: FieldSelector | None = None
    second_selector: FieldSelector | None = None
    duplicate_filter: FieldFilter | None = None
    destination_tag: str = ""
    control_value: str = ""
    ind1: str | None = None
    ind2: str | None = None
    subfields: tuple[tuple[str, str], ...] = ()
    subfield_code: str = ""
    subfield_value: str = ""
    position: str = "append"
    repeat_policy: str = "append"
    record_scope: str = "every"
    destination_policy: str = "append"
    subfield_occurrence: str = "every"
    remove_empty_field: bool = False
    keep_duplicate: str = "first"


@dataclass(frozen=True)
class RecordChangeResult:
    changed: bool
    skipped: bool = False
    reason: str | None = None
    fields_affected: int = 0
    subfields_affected: int = 0


def _is_control_tag(tag: str) -> bool:
    return isinstance(tag, str) and transforms.is_control_tag(tag)


def _valid_tag(tag: object, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(tag, str) or len(tag) != 3 or not tag.isascii() or not tag.isdigit():
        errors.append(f"{label} must be exactly three ASCII digits")
    elif tag == "000":
        errors.append(f"{label} cannot be 000 (the leader)")
    return errors


def _valid_indicator(value: object, label: str, *, allow_none: bool = True) -> list[str]:
    if value is None and allow_none:
        return []
    if not isinstance(value, str) or len(value) != 1:
        return [f"{label} must be one character or None"]
    return []


def _selector_unfiltered(selector: FieldSelector) -> bool:
    ff = selector.field_filter
    return (
        ff.ind1 == IndicatorFilter()
        and ff.ind2 == IndicatorFilter()
        and ff.subfield_code == ""
        and ff.match_mode == "exact"
        and ff.match_value == ""
        and not ff.ignore_case
    )


def _selector_tag(selector: object) -> str | None:
    if not isinstance(selector, FieldSelector):
        return None
    return selector.field_filter.tag if isinstance(selector.field_filter, FieldFilter) else None


def _canonical_kind(kind: object) -> str:
    return kind if isinstance(kind, str) else ""


def _supported(value: object, choices: frozenset[str]) -> bool:
    return isinstance(value, str) and value in choices


def validate_request(request: object) -> tuple[str, ...]:
    """Return all cataloger-facing request errors without touching a record."""

    if not isinstance(request, QuickFieldChangeRequest):
        return ("request must be a QuickFieldChangeRequest",)

    errors: list[str] = []
    kind = _canonical_kind(request.kind)
    if kind not in _KINDS:
        return ("operation kind is not supported",)

    if kind == "add-field":
        if request.selector is not None or request.second_selector is not None or request.duplicate_filter is not None:
            errors.append("add field does not use a field selector")
        errors.extend(_valid_tag(request.destination_tag, "destination tag"))
        if _is_control_tag(request.destination_tag):
            if not isinstance(request.control_value, str) or request.control_value == "":
                errors.append("control field value must be nonempty text")
            if request.subfields:
                errors.append("control fields cannot have subfields")
            if request.ind1 is not None or request.ind2 is not None:
                errors.append("control fields cannot have indicators")
        else:
            errors.extend(_valid_indicator(request.ind1, "indicator 1", allow_none=False))
            errors.extend(_valid_indicator(request.ind2, "indicator 2", allow_none=False))
            if not isinstance(request.control_value, str):
                errors.append("control value must be text")
            if not isinstance(request.subfields, tuple):
                errors.append("subfields must be a tuple of code/value pairs")
            elif len(request.subfields) > 100:
                errors.append("at most 100 subfields may be added")
            for index, pair in enumerate(request.subfields):
                if (
                    not isinstance(pair, tuple)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or not isinstance(pair[1], str)
                ):
                    errors.append(f"subfield row {index + 1} must contain code and text value")
                    continue
                code = pair[0]
                if len(code) != 1 or not code.isascii() or not code.isalnum() or code.lower() != code:
                    errors.append(f"subfield row {index + 1} code must be one lowercase letter or digit")
        if not _supported(request.record_scope, _RECORD_SCOPES):
            errors.append("record scope is not supported")
        return tuple(errors)

    if kind in _DUPLICATE_KINDS:
        if request.selector is not None or request.second_selector is not None:
            errors.append("duplicate removal uses duplicate_filter, not selector")
        if request.duplicate_filter is None:
            errors.append("duplicate filter is required")
        else:
            errors.extend(validate_field_filter(request.duplicate_filter))
        if not _supported(request.keep_duplicate, _KEEP_DUPLICATES):
            errors.append("keep duplicate must be first or last")
        return tuple(errors)

    if kind in _SWAP_KINDS:
        if request.selector is None or request.second_selector is None:
            errors.append("swap requires two selectors")
        else:
            errors.extend(validate_selector(request.selector, allow_every=False))
            errors.extend(validate_selector(request.second_selector, allow_every=False))
            if not errors:
                if request.selector.field_filter.tag != request.second_selector.field_filter.tag:
                    errors.append("swap selectors must use the same tag")
                if request.selector == request.second_selector:
                    errors.append("swap selectors must be different")
        return tuple(errors)

    if request.selector is None:
        errors.append("selector is required")
    else:
        errors.extend(validate_selector(request.selector))

    if kind in _ADD_SUBFIELD_KINDS:
        errors.extend(_validate_subfield_code(request.subfield_code, required=True))
        if not isinstance(request.subfield_value, str):
            errors.append("subfield value must be text")
        if not _supported(request.position, _POSITIONS):
            errors.append("position must be append or prepend")
        if not _supported(request.repeat_policy, _REPEAT_POLICIES):
            errors.append("repeat policy is not supported")
        if _is_control_tag(_selector_tag(request.selector)):
            errors.append("control fields cannot receive subfields")

    elif kind in _DELETE_SUBFIELD_KINDS:
        errors.extend(_validate_subfield_code(request.subfield_code, required=True))
        if not isinstance(request.subfield_value, str):
            errors.append("subfield value must be text")
        if not _supported(request.subfield_occurrence, _SUBFIELD_OCCURRENCES):
            errors.append("subfield occurrence must be first or every")
        if not isinstance(request.remove_empty_field, bool):
            errors.append("remove empty field must be true or false")
        if _is_control_tag(_selector_tag(request.selector)):
            errors.append("control fields cannot have subfields removed")

    elif kind in _COPY_KINDS:
        errors.extend(_valid_tag(request.destination_tag, "destination tag"))
        if not _supported(request.destination_policy, _DESTINATION_POLICIES):
            errors.append("destination policy is not supported")
        source_tag = _selector_tag(request.selector)
        if source_tag is not None:
            source_control = _is_control_tag(source_tag)
            destination_control = _is_control_tag(request.destination_tag)
            if source_control != destination_control:
                errors.append("source and destination must both be control fields or both be data fields")

    elif kind in _DELETE_KINDS:
        pass

    elif kind in _MOVE_KINDS:
        errors.extend(_valid_tag(request.destination_tag, "destination tag"))
        source_tag = _selector_tag(request.selector)
        if source_tag is not None:
            source_control = _is_control_tag(source_tag)
            destination_control = _is_control_tag(request.destination_tag)
            if source_control != destination_control:
                errors.append("source and destination must both be control fields or both be data fields")

    elif kind in _SET_INDICATOR_KINDS:
        errors.extend(_valid_indicator(request.ind1, "indicator 1"))
        errors.extend(_valid_indicator(request.ind2, "indicator 2"))
        if request.ind1 is None and request.ind2 is None:
            errors.append("at least one indicator must change")
        if _is_control_tag(_selector_tag(request.selector)):
            errors.append("control fields cannot have indicators")

    return tuple(errors)


def _validate_subfield_code(code: object, *, required: bool) -> list[str]:
    if not isinstance(code, str) or (required and not code):
        return ["subfield code is required"]
    if code and (len(code) != 1 or not code.isascii() or not code.isalnum() or code.lower() != code):
        return ["subfield code must be one lowercase letter or digit"]
    return []


def _indicator_payload(value: IndicatorFilter) -> dict[str, object]:
    return {"mode": value.mode, "value": value.value}


def _filter_payload(value: FieldFilter) -> dict[str, object]:
    return {
        "tag": value.tag,
        "ind1": _indicator_payload(value.ind1),
        "ind2": _indicator_payload(value.ind2),
        "subfield_code": value.subfield_code,
        "match_mode": value.match_mode,
        "match_value": value.match_value,
        "ignore_case": value.ignore_case,
    }


def _selector_payload(value: FieldSelector | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "field_filter": _filter_payload(value.field_filter),
        "occurrence": {"mode": value.occurrence.mode, "number": value.occurrence.number},
    }


def request_to_payload(request: QuickFieldChangeRequest) -> dict[str, object]:
    """Convert an immutable request into JSON-compatible primitive values."""

    if not isinstance(request, QuickFieldChangeRequest):
        raise ValueError("request must be a QuickFieldChangeRequest")
    return {
        "kind": request.kind,
        "selector": _selector_payload(request.selector),
        "second_selector": _selector_payload(request.second_selector),
        "duplicate_filter": _filter_payload(request.duplicate_filter)
        if request.duplicate_filter is not None
        else None,
        "destination_tag": request.destination_tag,
        "control_value": request.control_value,
        "ind1": request.ind1,
        "ind2": request.ind2,
        "subfields": [[code, value] for code, value in request.subfields],
        "subfield_code": request.subfield_code,
        "subfield_value": request.subfield_value,
        "position": request.position,
        "repeat_policy": request.repeat_policy,
        "record_scope": request.record_scope,
        "destination_policy": request.destination_policy,
        "subfield_occurrence": request.subfield_occurrence,
        "remove_empty_field": request.remove_empty_field,
        "keep_duplicate": request.keep_duplicate,
    }


def _indicator_from_payload(value: object, label: str) -> IndicatorFilter:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an indicator filter object")
    try:
        return IndicatorFilter(mode=value["mode"], value=value.get("value", ""))
    except KeyError as exc:
        raise ValueError(f"{label} is missing {exc.args[0]}") from exc


def _filter_from_payload(value: object, label: str) -> FieldFilter:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a field filter object")
    try:
        return FieldFilter(
            tag=value["tag"],
            ind1=_indicator_from_payload(value.get("ind1", {"mode": "any", "value": ""}), f"{label} indicator 1"),
            ind2=_indicator_from_payload(value.get("ind2", {"mode": "any", "value": ""}), f"{label} indicator 2"),
            subfield_code=value.get("subfield_code", ""),
            match_mode=value.get("match_mode", "exact"),
            match_value=value.get("match_value", ""),
            ignore_case=value.get("ignore_case", False),
        )
    except KeyError as exc:
        raise ValueError(f"{label} is missing {exc.args[0]}") from exc


def _selector_from_payload(value: object, label: str) -> FieldSelector | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a selector object")
    field_filter = _filter_from_payload(value.get("field_filter"), f"{label} field filter")
    occurrence_value = value.get("occurrence", {"mode": "first", "number": None})
    if not isinstance(occurrence_value, dict):
        raise ValueError(f"{label} occurrence must be an object")
    return FieldSelector(
        field_filter=field_filter,
        occurrence=Occurrence(
            mode=occurrence_value.get("mode", "first"),
            number=occurrence_value.get("number"),
        ),
    )


def request_from_payload(payload: object) -> QuickFieldChangeRequest:
    """Deserialize a canonical payload and fail closed on malformed shapes."""

    if isinstance(payload, QuickFieldChangeRequest):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("request payload must be an object")
    try:
        subfields_raw = payload.get("subfields", ())
        if isinstance(subfields_raw, list):
            subfields = tuple(tuple(pair) for pair in subfields_raw)
        elif isinstance(subfields_raw, tuple):
            subfields = tuple(tuple(pair) for pair in subfields_raw)
        else:
            subfields = subfields_raw
        request = QuickFieldChangeRequest(
            kind=payload["kind"],
            selector=_selector_from_payload(payload.get("selector"), "selector"),
            second_selector=_selector_from_payload(payload.get("second_selector"), "second selector"),
            duplicate_filter=_filter_from_payload(payload["duplicate_filter"], "duplicate filter")
            if payload.get("duplicate_filter") is not None
            else None,
            destination_tag=payload.get("destination_tag", ""),
            control_value=payload.get("control_value", ""),
            ind1=payload.get("ind1"),
            ind2=payload.get("ind2"),
            subfields=subfields,
            subfield_code=payload.get("subfield_code", ""),
            subfield_value=payload.get("subfield_value", ""),
            position=payload.get("position", "append"),
            repeat_policy=payload.get("repeat_policy", "append"),
            record_scope=payload.get("record_scope", "every"),
            destination_policy=payload.get("destination_policy", "append"),
            subfield_occurrence=payload.get("subfield_occurrence", "every"),
            remove_empty_field=payload.get("remove_empty_field", False),
            keep_duplicate=payload.get("keep_duplicate", "first"),
        )
    except KeyError as exc:
        raise ValueError(f"request payload is missing {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("request payload has invalid field types") from exc
    return request


def _skip(reason: str) -> RecordChangeResult:
    return RecordChangeResult(False, skipped=True, reason=reason)


def _resolved(record: Record, selector: FieldSelector) -> tuple[Field, ...] | RecordChangeResult:
    result = resolve_fields(record, selector)
    if not result.fields:
        return _skip(result.skip_reason or "no-filtered-fields")
    return result.fields


def _field_signature(field: Field) -> tuple[Any, ...]:
    if field.is_control_field():
        return (field.tag, "control", field.data)
    return (
        field.tag,
        "data",
        tuple(field.indicators),
        tuple((sf.code, sf.value) for sf in field.subfields),
    )


def _same_data_field(left: Field, right: Field) -> bool:
    return _field_signature(left) == _field_signature(right)


def _match_subfield_value(value: str, request: QuickFieldChangeRequest, selector: FieldSelector) -> bool:
    ff = selector.field_filter
    # The selector's matcher is the optional value matcher for Delete subfield
    # when the dedicated value is omitted.  This also keeps raw regex work at
    # the same matching boundary as the selector module.
    expected = request.subfield_value
    mode = ff.match_mode
    ignore_case = ff.ignore_case
    if expected == "" and ff.subfield_code == request.subfield_code and ff.match_value:
        expected = ff.match_value
    if expected == "":
        return True
    candidate, target = value, expected
    if mode == "raw_regex":
        flags = re.IGNORECASE if ignore_case else 0
        return re.search(target, candidate, flags) is not None
    if ignore_case:
        candidate, target = candidate.casefold(), target.casefold()
    if mode == "contains":
        return target in candidate
    if mode == "starts_with":
        return candidate.startswith(target)
    if mode == "ends_with":
        return candidate.endswith(target)
    return candidate == target


def _apply_add_field(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    tag = request.destination_tag
    if _is_control_tag(tag):
        candidate = Field(tag=tag, data=request.control_value)
    else:
        candidate = transforms.make_field(tag, request.ind1 or "", request.ind2 or "", *request.subfields)
    existing = record.get_fields(tag)
    scope = request.record_scope
    if scope in {"tag_absent", "when_tag_absent", "if_tag_absent"} and existing:
        return RecordChangeResult(False)
    if scope in {"identical_absent", "when_identical_absent", "if_identical_absent"}:
        if any(_same_data_field(candidate, field) for field in existing):
            return RecordChangeResult(False)
    record.add_ordered_field(candidate)
    return RecordChangeResult(True, fields_affected=1)


def _apply_add_subfield(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    selected = _resolved(record, request.selector)  # type: ignore[arg-type]
    if isinstance(selected, RecordChangeResult):
        return selected
    position = "start" if request.position in {"prepend", "start"} else "end"
    skip_existing = request.repeat_policy in {"skip", "skip_identical", "skip-if-identical", "skip_if_identical"}
    changed_fields = 0
    added = 0
    if request.selector is not None and request.selector.occurrence.mode == "every" and _selector_unfiltered(request.selector) and position == "end" and not skip_existing:
        transforms.add_subfield_to_fields(record, request.selector.field_filter.tag, request.subfield_code, request.subfield_value, position="end")
        return RecordChangeResult(True, fields_affected=len(selected), subfields_affected=len(selected))
    for field in selected:
        if field.is_control_field():
            continue
        pair = (request.subfield_code, request.subfield_value)
        if skip_existing and any((sf.code, sf.value) == pair for sf in field.subfields):
            continue
        sf = Subfield(code=request.subfield_code, value=request.subfield_value)
        if position == "start":
            field.subfields.insert(0, sf)
        else:
            field.subfields.append(sf)
        changed_fields += 1
        added += 1
    return RecordChangeResult(bool(added), fields_affected=changed_fields, subfields_affected=added)


def _apply_delete_subfield(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    selected = _resolved(record, request.selector)  # type: ignore[arg-type]
    if isinstance(selected, RecordChangeResult):
        return selected
    changed_fields = 0
    removed = 0
    remove_fields: list[Field] = []
    ff = request.selector.field_filter if request.selector is not None else None
    can_use_helper = (
        request.selector is not None
        and request.selector.occurrence.mode == "every"
        and _selector_unfiltered(request.selector)
        and request.subfield_occurrence == "every"
        and not request.remove_empty_field
    )
    if can_use_helper and request.subfield_value == "":
        before = {id(field): len(field.subfields) for field in selected}
        transforms.delete_subfields(record, request.selector.field_filter.tag, request.subfield_code)
        for field in selected:
            delta = before[id(field)] - len(field.subfields)
            if delta:
                changed_fields += 1
                removed += delta
        return RecordChangeResult(bool(removed), fields_affected=changed_fields, subfields_affected=removed)
    for field in selected:
        if field.is_control_field():
            continue
        indexes = [
            i for i, sf in enumerate(field.subfields)
            if sf.code == request.subfield_code and _match_subfield_value(sf.value, request, request.selector)  # type: ignore[arg-type]
        ]
        if request.subfield_occurrence == "first" and indexes:
            indexes = indexes[:1]
        if not indexes:
            continue
        drop = set(indexes)
        field.subfields = [sf for i, sf in enumerate(field.subfields) if i not in drop]
        changed_fields += 1
        removed += len(indexes)
        if request.remove_empty_field and not field.subfields:
            remove_fields.append(field)
    if remove_fields:
        remove_ids = {id(field) for field in remove_fields}
        record.fields[:] = [field for field in record.fields if id(field) not in remove_ids]
    return RecordChangeResult(bool(removed), fields_affected=changed_fields, subfields_affected=removed)


def _copy_clone(field: Field, destination_tag: str) -> Field:
    clone = copy.deepcopy(field)
    clone.tag = destination_tag
    return clone


def _apply_copy_field(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    selected = _resolved(record, request.selector)  # type: ignore[arg-type]
    if isinstance(selected, RecordChangeResult):
        return selected
    destination = request.destination_tag
    candidates = [_copy_clone(field, destination) for field in selected]
    policy = request.destination_policy
    if policy in {"replace_all", "replace-all"}:
        old_count = len(record.get_fields(destination))
        record.fields[:] = [field for field in record.fields if field.tag != destination]
        for candidate in candidates:
            record.add_ordered_field(candidate)
        return RecordChangeResult(bool(candidates or old_count), fields_affected=len(candidates) + old_count)
    added = 0
    for candidate in candidates:
        if policy in {"skip", "skip_identical", "skip-if-identical"} and any(
            _same_data_field(candidate, existing) for existing in record.get_fields(destination)
        ):
            continue
        record.add_ordered_field(candidate)
        added += 1
    return RecordChangeResult(bool(added), fields_affected=added)


def _apply_delete_field(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    selected = _resolved(record, request.selector)  # type: ignore[arg-type]
    if isinstance(selected, RecordChangeResult):
        return selected
    if request.selector is not None and request.selector.occurrence.mode == "every" and _selector_unfiltered(request.selector):
        before = len(record.get_fields(request.selector.field_filter.tag))
        transforms.delete_tags(record, request.selector.field_filter.tag)
        return RecordChangeResult(bool(before), fields_affected=before)
    selected_ids = {id(field) for field in selected}
    record.fields[:] = [field for field in record.fields if id(field) not in selected_ids]
    return RecordChangeResult(bool(selected), fields_affected=len(selected))


def _apply_move_field(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    selected = _resolved(record, request.selector)  # type: ignore[arg-type]
    if isinstance(selected, RecordChangeResult):
        return selected
    destination = request.destination_tag
    changed = 0
    for field in selected:
        if field.tag != destination:
            field.tag = destination
            changed += 1
    return RecordChangeResult(bool(changed), fields_affected=changed)


def _apply_set_indicators(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    selected = _resolved(record, request.selector)  # type: ignore[arg-type]
    if isinstance(selected, RecordChangeResult):
        return selected
    changed = 0
    for field in selected:
        if field.is_control_field():
            continue
        existing = list(field.indicators)
        replacement = [
            existing[0] if request.ind1 is None else request.ind1,
            existing[1] if request.ind2 is None else request.ind2,
        ]
        if existing != replacement:
            field.indicators = replacement
            changed += 1
    return RecordChangeResult(bool(changed), fields_affected=changed)


def _apply_swap(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    first = _resolved(record, request.selector)  # type: ignore[arg-type]
    if isinstance(first, RecordChangeResult):
        return _skip("swap-first-absent")
    second = _resolved(record, request.second_selector)  # type: ignore[arg-type]
    if isinstance(second, RecordChangeResult):
        return _skip("swap-second-absent")
    first_field, second_field = first[0], second[0]
    if first_field is second_field:
        return _skip("swap-same-field")
    first_index = next(i for i, field in enumerate(record.fields) if field is first_field)
    second_index = next(i for i, field in enumerate(record.fields) if field is second_field)
    record.fields[first_index], record.fields[second_index] = record.fields[second_index], record.fields[first_index]
    return RecordChangeResult(True, fields_affected=2)


def _apply_remove_duplicates(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    field_filter = request.duplicate_filter
    assert field_filter is not None
    selected = matching_fields(record, field_filter)
    if not selected:
        return _skip("no-filtered-fields")
    groups: dict[tuple[Any, ...], list[Field]] = {}
    for field in selected:
        groups.setdefault(_field_signature(field), []).append(field)
    remove_ids: set[int] = set()
    for fields in groups.values():
        if len(fields) <= 1:
            continue
        survivors = fields[:1] if request.keep_duplicate == "first" else fields[-1:]
        survivor_ids = {id(field) for field in survivors}
        remove_ids.update(id(field) for field in fields if id(field) not in survivor_ids)
    if not remove_ids:
        return RecordChangeResult(False)
    record.fields[:] = [field for field in record.fields if id(field) not in remove_ids]
    return RecordChangeResult(True, fields_affected=len(remove_ids))


def apply_quick_field_change(record: Record, request: QuickFieldChangeRequest) -> RecordChangeResult:
    """Validate and apply exactly one focused change to one record."""

    if not isinstance(record, Record):
        raise ValueError("record must be a pymarc Record")
    errors = validate_request(request)
    if errors:
        raise ValueError("; ".join(errors))
    kind = _canonical_kind(request.kind)
    if kind == "add-field":
        return _apply_add_field(record, request)
    if kind in _ADD_SUBFIELD_KINDS:
        return _apply_add_subfield(record, request)
    if kind in _DELETE_SUBFIELD_KINDS:
        return _apply_delete_subfield(record, request)
    if kind in _COPY_KINDS:
        return _apply_copy_field(record, request)
    if kind in _DELETE_KINDS:
        return _apply_delete_field(record, request)
    if kind in _MOVE_KINDS:
        return _apply_move_field(record, request)
    if kind in _SET_INDICATOR_KINDS:
        return _apply_set_indicators(record, request)
    if kind in _SWAP_KINDS:
        return _apply_swap(record, request)
    return _apply_remove_duplicates(record, request)


def prepare_quick_field_change_adapter(payload: object):
    """Prepare the fixed one-record adapter from a JSON-compatible payload."""

    request = request_from_payload(payload)
    errors = validate_request(request)
    if errors:
        raise ValueError("; ".join(errors))
    return lambda record: asdict(apply_quick_field_change(record, request))
