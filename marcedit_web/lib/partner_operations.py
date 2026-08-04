"""Deterministic pymarc operations for reviewed partner-task patterns."""

from __future__ import annotations

import copy
from typing import Any

from pymarc import Field, Record, Subfield

from .field_predicates import field_matches


def is_control_tag(tag: str) -> bool:
    return len(tag) == 3 and tag.isdigit() and tag.startswith("00")


_OCCURRENCES = {"first", "last", "all"}
_EXISTING_ACTIONS = {"append", "replace", "skip"}
DEFAULT_MAX_FIELDS_PER_BATCH = 10_000
_BATCH_TOTALS: dict[str, int] = {}
_BATCH_CONTEXT = ""


def reset_partner_batch_totals() -> None:
    """Reset accounting for one sandbox invocation."""
    _BATCH_TOTALS.clear()


def set_partner_batch_context(context: str) -> None:
    """Set the task index used to keep same-position operations distinct."""
    global _BATCH_CONTEXT
    _BATCH_CONTEXT = str(context)


def record_partner_result(operation_key: str, result: dict[str, Any]) -> None:
    """Record fields created by one partner operation invocation."""
    if not isinstance(result, dict):
        raise ValueError("partner operation result must be an object")
    try:
        created = int(result.get("destination_fields_created", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("partner operation created count is invalid") from exc
    if isinstance(result.get("destination_fields_created", 0), bool) or created < 0:
        raise ValueError("partner operation created count is invalid")
    key = (
        f"{_BATCH_CONTEXT}:{operation_key}"
        if _BATCH_CONTEXT
        else str(operation_key)
    )
    total = _BATCH_TOTALS.get(key, 0) + created
    if total > 2_147_483_647:
        raise ValueError("partner operation batch count exceeds supported limit")
    _BATCH_TOTALS[key] = total


def get_partner_batch_totals() -> dict[str, int]:
    """Return bounded accounting totals for the current sandbox process."""
    return dict(_BATCH_TOTALS)


def _clone_field(field: Field, tag: str) -> Field:
    if field.is_control_field():
        return Field(tag=tag, data=field.data)
    return Field(
        tag=tag,
        indicators=list(field.indicators),
        subfields=[Subfield(code=sf.code, value=sf.value) for sf in field.subfields],
    )


def _select_occurrences(fields: list[Field], occurrence: str) -> list[Field]:
    if occurrence not in _OCCURRENCES:
        raise ValueError("occurrence must be first, last, or all")
    if occurrence == "first":
        return fields[:1]
    if occurrence == "last":
        return fields[-1:] if fields else []
    return fields


def _empty_result() -> dict[str, int]:
    return {
        "records_inspected": 1,
        "source_fields_matched": 0,
        "destination_fields_created": 0,
        "existing_fields_replaced": 0,
        "records_skipped": 0,
    }


def copy_fields_with_policy(
    record: Record,
    *,
    source_tag: str,
    destination_tag: str,
    occurrence: str = "all",
    existing_field_action: str = "append",
    predicate: dict[str, Any] | None = None,
    max_fields_per_record: int = 100,
) -> dict[str, int]:
    """Copy selected source fields with explicit occurrence/collision policy.

    All candidates are cloned and validated before the record is mutated. This
    makes expansion limits and policy errors fail without partial output.
    """
    source_tag = str(source_tag).strip()
    destination_tag = str(destination_tag).strip()
    if not source_tag or not destination_tag:
        raise ValueError("source and destination tags are required")
    if is_control_tag(source_tag) != is_control_tag(destination_tag):
        raise ValueError(
            "source and destination must both be control fields or both be data fields"
        )
    if existing_field_action not in _EXISTING_ACTIONS:
        raise ValueError("existing field action is not supported")
    if max_fields_per_record <= 0:
        raise ValueError("max_fields_per_record must be positive")

    sources = list(record.get_fields(source_tag))
    if predicate:
        sources = [field for field in sources if field_matches(field, predicate)]
    selected = _select_occurrences(sources, occurrence)
    result = _empty_result()
    result["source_fields_matched"] = len(selected)
    if not selected:
        return result

    candidates = [_clone_field(field, destination_tag) for field in selected]
    if len(candidates) > max_fields_per_record:
        raise ValueError(
            "partner operation expansion bound exceeded: "
            f"{len(candidates)} fields > {max_fields_per_record}"
        )

    existing = list(record.get_fields(destination_tag))
    if existing_field_action == "skip" and existing:
        result["records_skipped"] = 1
        return result

    if existing_field_action == "replace":
        result["existing_fields_replaced"] = len(existing)
        retained = [field for field in record.fields if field.tag != destination_tag]
        record.fields[:] = retained

    for field in candidates:
        record.add_ordered_field(copy.deepcopy(field))
    result["destination_fields_created"] = len(candidates)
    return result


def _resolve_part(
    field: Field,
    part: dict[str, Any],
    record: Record | None = None,
) -> str | None:
    kind = part.get("type")
    if kind == "text":
        return str(part.get("value", ""))
    if kind == "source_subfield":
        values = field.get_subfields(str(part.get("code", "")))
        return values[0] if values else None
    if kind == "source_indicator":
        index = int(part.get("index", 1)) - 1
        if field.is_control_field() or index not in (0, 1):
            return None
        return field.indicators[index]
    if kind == "source_control_field":
        if record is None:
            return None
        source = record.get(str(part.get("tag", "")))
        return None if source is None else str(source.data)
    raise ValueError(f"unsupported partner template part {kind!r}")


def _render_template(
    field: Field,
    templates: list[dict[str, Any]],
    record: Record | None = None,
) -> list[Subfield] | None:
    rendered: list[Field] = []
    for template in templates:
        code = str(template.get("code", "")).strip()
        parts = template.get("parts")
        if len(code) != 1 or not isinstance(parts, list):
            raise ValueError("partner subfield template requires code and parts")
        values: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("partner template part must be an object")
            value = _resolve_part(field, part, record)
            if value is None:
                return None
            values.append(value)
        rendered.append(Subfield(code=code, value="".join(values)))
    return rendered


def build_fields_for_matches(
    record: Record,
    *,
    source_tag: str,
    destination_tag: str,
    indicators: list[str],
    subfield_templates: list[dict[str, Any]],
    occurrence: str = "all",
    missing_source_action: str = "skip_field",
    existing_field_action: str = "append",
    predicate: dict[str, Any] | None = None,
    max_fields_per_record: int = 100,
) -> dict[str, int]:
    """Build destination fields from each selected source field."""
    if missing_source_action not in {"skip_field", "fail"}:
        raise ValueError("missing source action is not supported")
    if len(indicators) != 2:
        raise ValueError("partner field indicators must contain two values")
    source_fields = list(record.get_fields(str(source_tag).strip()))
    if predicate:
        source_fields = [f for f in source_fields if field_matches(f, predicate)]
    selected = _select_occurrences(source_fields, occurrence)
    result = _empty_result()
    result["source_fields_matched"] = len(selected)
    candidates: list[Field] = []
    for source in selected:
        subfields = _render_template(source, subfield_templates, record)
        if subfields is None:
            if missing_source_action == "fail":
                raise ValueError("source value is missing for partner field template")
            continue
        candidates.append(
            Field(
                tag=str(destination_tag).strip(),
                indicators=list(indicators),
                subfields=subfields,
            )
        )
    if len(candidates) > max_fields_per_record:
        raise ValueError(
            "partner operation expansion bound exceeded: "
            f"{len(candidates)} fields > {max_fields_per_record}"
        )
    if not candidates:
        return result
    destination_tag = str(destination_tag).strip()
    existing = list(record.get_fields(destination_tag))
    if existing_field_action not in _EXISTING_ACTIONS:
        raise ValueError("existing field action is not supported")
    if existing_field_action == "skip" and existing:
        result["records_skipped"] = 1
        return result
    if existing_field_action == "replace":
        result["existing_fields_replaced"] = len(existing)
        record.fields[:] = [f for f in record.fields if f.tag != destination_tag]
    for candidate in candidates:
        record.add_ordered_field(candidate)
    result["destination_fields_created"] = len(candidates)
    return result


def apply_institution_profile(
    record: Record,
    *,
    source_tag: str,
    rows: list[dict[str, Any]],
    occurrence: str = "all",
    max_fields_per_record: int = 100,
) -> dict[str, int]:
    """Apply editable institution mapping rows to selected source fields."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("institution profile must contain at least one row")
    source_fields = _select_occurrences(
        list(record.get_fields(str(source_tag).strip())), occurrence
    )
    result = _empty_result()
    result["source_fields_matched"] = len(source_fields)
    staged: list[tuple[str, Field]] = []
    for source in source_fields:
        for row in rows:
            destination_tag = str(row.get("destination_tag", "")).strip()
            indicators = row.get("indicators", [" ", " "])
            templates = [
                {"code": code, "parts": [{"type": "text", "value": value}]}
                if "{source_subfield:" not in str(value)
                else {
                    "code": code,
                    "parts": [
                        {"type": "source_subfield", "code": str(value)[17:-1]}
                    ],
                }
                for code, value in row.get("subfields", [])
            ]
            subfields = _render_template(source, templates)
            if subfields is None:
                continue
            staged.append(
                (
                    destination_tag,
                    Field(tag=destination_tag, indicators=list(indicators), subfields=subfields),
                )
            )
    if len(staged) > max_fields_per_record:
        raise ValueError(
            "partner operation expansion bound exceeded: "
            f"{len(staged)} fields > {max_fields_per_record}"
        )
    for destination_tag, field in staged:
        record.add_ordered_field(field)
    result["destination_fields_created"] = len(staged)
    return result
