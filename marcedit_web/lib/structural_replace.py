"""Deterministic structural Find/Replace operations (TASK-184)."""

from __future__ import annotations

import copy
import re
from typing import Any

from pymarc import Field, Record, Subfield


TARGET_KINDS = {"subfield", "all_subfields", "data_field", "field_tag", "indicators", "tag_range"}
ACTIONS = {"replace_matched_text", "replace_field", "retag", "set_indicators"}
MATCH_MODES = {
    "all",
    "contains",
    "starts_with",
    "ends_with",
    "whole_value",
    "structured",
    "raw_regex",
}
_TAG = re.compile(r"^\d{3}$")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _validate_tag(tag: str, label: str) -> None:
    if not isinstance(tag, str) or _TAG.fullmatch(tag) is None:
        raise ValueError(f"{label} must be exactly three numeric characters")


def validate_request(**request: Any) -> tuple[str, ...]:
    errors: list[str] = []
    target = request.get("target_kind")
    action = request.get("action")
    mode = request.get("match_mode")
    if target not in TARGET_KINDS:
        errors.append("structural target is not supported")
    if action not in ACTIONS:
        errors.append("structural action is not supported")
    if mode not in MATCH_MODES:
        errors.append("structural match mode is not supported")
    tag = request.get("tag", "")
    if target != "tag_range":
        try:
            _validate_tag(tag, "Tag")
        except ValueError as exc:
            errors.append(str(exc))
    allowed_actions = {
        "subfield": {"replace_matched_text"},
        "all_subfields": {"replace_matched_text"},
        "data_field": {"replace_field"},
        "field_tag": {"retag"},
        "indicators": {"set_indicators"},
        "tag_range": {"retag", "set_indicators"},
    }
    if target in allowed_actions and action not in allowed_actions[target]:
        errors.append(
            f"action {action!r} is incompatible with target {target!r}"
        )
    if target == "tag_range":
        start = request.get("start_tag", "")
        end = request.get("end_tag", "")
        try:
            _validate_tag(start, "Start tag")
            _validate_tag(end, "End tag")
            if int(start) > int(end):
                errors.append("start tag cannot exceed end tag")
            if (int(start) < 10) != (int(end) < 10):
                errors.append("tag range cannot cross the control/data boundary")
            elif int(start) < 10 and action != "retag":
                errors.append(
                    "control-field ranges support retagging only; "
                    "subfield, indicator, and complete-field actions are invalid"
                )
        except ValueError as exc:
            errors.append(str(exc))
    if target in {"subfield", "all_subfields"} and target == "subfield":
        if not re.fullmatch(r"[a-z0-9]", str(request.get("subfield", ""))):
            errors.append("subfield code must be one lowercase letter or digit")
    if target in {"field_tag", "indicators", "tag_range"} and request.get("subfield"):
        errors.append("subfield code is not available for this structural target")
    if target in {"data_field", "field_tag", "indicators", "tag_range"}:
        if tag and tag.isdigit() and int(tag) < 10:
            errors.append("structural data targets cannot use control fields")
    if action == "retag":
        try:
            _validate_tag(request.get("destination_tag", ""), "Destination tag")
            if target == "tag_range":
                start = request.get("start_tag", "")
                destination = request.get("destination_tag", "")
                if start.isdigit() and destination.isdigit():
                    if (int(start) < 10) != (int(destination) < 10):
                        errors.append(
                            "retag destination must stay in the same "
                            "control/data field class"
                        )
        except ValueError as exc:
            errors.append(str(exc))
    if action == "set_indicators":
        for name in ("new_ind1", "new_ind2"):
            if not isinstance(request.get(name, " "), str) or len(request.get(name, " ")) != 1:
                errors.append(f"{name} must be one character")
        for name in ("match_ind1", "match_ind2"):
            value = request.get(name, "*")
            if not isinstance(value, str) or len(value) != 1:
                errors.append(f"{name} must be one character or '*'")
    if action == "replace_field":
        if not isinstance(request.get("replacement_subfields"), list) or not request.get("replacement_subfields"):
            errors.append("replacement subfields are required")
    if mode == "structured":
        try:
            _compile_structured_pattern(request.get("pattern_pieces", []))
            _replacement_from_pieces(request.get("replacement_pieces", []), set(_capture_names(request.get("pattern_pieces", []))))
        except ValueError as exc:
            errors.append(str(exc))
    elif mode == "all":
        if request.get("find", ""):
            errors.append("Find must be empty when Match is every selected field")
        if action not in {"retag", "set_indicators"}:
            errors.append("every-selected-field matching is only valid for retag or set indicators")
    else:
        find = request.get("find", "")
        if not isinstance(find, str):
            errors.append("find must be text")
        elif not find:
            errors.append("Find text is required; choose every selected field explicitly when no text match is intended")
        elif mode == "raw_regex":
            try:
                pattern = re.compile(
                    find,
                    re.IGNORECASE if request.get("ignore_case") else 0,
                )
                if action == "replace_matched_text":
                    pattern.sub(str(request.get("replacement", "")), "")
            except re.error as exc:
                errors.append(f"invalid raw-regex replacement: {exc}")
    return tuple(errors)


def normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(request)
    normalized.setdefault("action", "replace_matched_text")
    normalized.setdefault("match_mode", "contains")
    normalized.setdefault("occurrences", "all")
    normalized.setdefault("ignore_case", False)
    normalized.setdefault("replacement", "")
    normalized.setdefault("replacement_subfields", [])
    normalized.setdefault("replacement_pieces", [])
    normalized.setdefault("pattern_pieces", [])
    normalized.setdefault("subfield", "")
    normalized.setdefault("tag", "")
    return normalized


def _capture_names(pieces: Any) -> list[str]:
    names: list[str] = []
    for piece in pieces if isinstance(pieces, list) else []:
        if not isinstance(piece, dict):
            raise ValueError("pattern pieces must be objects")
        name = piece.get("name")
        if name is not None:
            if not isinstance(name, str) or _NAME.fullmatch(name) is None:
                raise ValueError("capture names must be simple identifiers")
            if name in names:
                raise ValueError(f"capture name is repeated: {name}")
            names.append(name)
    return names


def _compile_structured_pattern(pieces: Any) -> tuple[re.Pattern, list[str]]:
    if not isinstance(pieces, list) or not pieces:
        raise ValueError("at least one structured pattern piece is required")
    names = _capture_names(pieces)
    parts: list[str] = []
    for piece in pieces:
        kind = piece.get("type")
        if kind == "literal":
            parts.append(re.escape(str(piece.get("value", ""))))
        elif kind == "any_text":
            parts.append(f"(?P<{piece['name']}>.+?)" if piece.get("name") else ".+?")
        elif kind == "digits":
            parts.append(f"(?P<{piece['name']}>\\d+)" if piece.get("name") else "\\d+")
        elif kind == "charset":
            chars = str(piece.get("value", ""))
            if not chars:
                raise ValueError("character-set pattern piece cannot be empty")
            atom = f"[{re.escape(chars)}]+"
            parts.append(f"(?P<{piece['name']}>{atom})" if piece.get("name") else atom)
        elif kind == "start":
            parts.append("^")
        elif kind == "end":
            parts.append("$")
        else:
            raise ValueError(f"unsupported structured pattern piece: {kind!r}")
    try:
        return re.compile("".join(parts)), names
    except re.error as exc:
        raise ValueError(f"invalid structured pattern: {exc}") from exc


def _replacement_from_pieces(pieces: Any, capture_names: set[str]) -> str:
    output: list[str] = []
    for piece in pieces if isinstance(pieces, list) else []:
        if not isinstance(piece, dict):
            raise ValueError("replacement pieces must be objects")
        kind = piece.get("type")
        if kind == "literal":
            output.append(str(piece.get("value", "")))
        elif kind == "capture":
            name = piece.get("name")
            if name not in capture_names:
                raise ValueError(f"replacement references unknown capture: {name}")
            output.append(f"\\g<{name}>")
        else:
            raise ValueError(f"unsupported replacement piece: {kind!r}")
    return "".join(output)


def _matcher(request: dict[str, Any]) -> tuple[re.Pattern, str]:
    mode = request["match_mode"]
    if mode == "all":
        return re.compile(r"(?s:.*)"), ""
    if mode == "structured":
        pattern, _ = _compile_structured_pattern(request["pattern_pieces"])
        return pattern, _replacement_from_pieces(
            request.get("replacement_pieces", []),
            set(_capture_names(request["pattern_pieces"])),
        )
    pattern = request.get("find", "")
    if mode != "raw_regex":
        pattern = re.escape(pattern)
        if mode == "starts_with":
            pattern = "^" + pattern
        elif mode == "ends_with":
            pattern += "$"
        elif mode == "whole_value":
            pattern = "^" + pattern + "$"
    try:
        return re.compile(pattern, re.IGNORECASE if request.get("ignore_case") else 0), str(request.get("replacement", ""))
    except re.error as exc:
        raise ValueError(f"invalid structural regular expression: {exc}") from exc


def _in_range(tag: str, request: dict[str, Any]) -> bool:
    if request["target_kind"] != "tag_range":
        return tag == request.get("tag")
    return int(request["start_tag"]) <= int(tag) <= int(request["end_tag"])


def apply_structural_find_replace(record: Record, **raw_request: Any) -> dict[str, int]:
    request = normalize_request(raw_request)
    errors = validate_request(**request)
    if errors:
        raise ValueError("; ".join(errors))
    matcher, replacement = _matcher(request)
    result = {"matched_fields": 0, "changed_fields": 0, "matched_occurrences": 0}
    candidates = [field for field in record.fields if _in_range(field.tag, request)]
    for field in candidates:
        if (
            field.tag in {"000"}
            or (
                field.tag.isdigit()
                and int(field.tag) < 10
                and request["action"] != "retag"
            )
        ):
            continue
        values = [field.value() or ""]
        if request["target_kind"] in {"subfield", "all_subfields"}:
            values = [
                sf.value for sf in field.subfields
                if request["target_kind"] == "all_subfields" or sf.code == request.get("subfield")
            ]
        if request["target_kind"] == "indicators":
            match_ind1 = request.get("match_ind1", "*")
            match_ind2 = request.get("match_ind2", "*")
            if (match_ind1 != "*" and field.indicators[0] != match_ind1) or (
                match_ind2 != "*" and field.indicators[1] != match_ind2
            ):
                continue
        matched = any(matcher.search(value) for value in values)
        if not matched:
            continue
        result["matched_fields"] += 1
        if request["action"] == "replace_field":
            replacement_field = Field(
                tag=field.tag,
                indicators=[request.get("replacement_ind1", " "), request.get("replacement_ind2", " ")],
                subfields=[Subfield(str(code), str(value)) for code, value in request["replacement_subfields"]],
            )
            index = record.fields.index(field)
            record.fields[index] = replacement_field
            result["changed_fields"] += 1
            continue
        if request["action"] == "retag":
            # Retagging preserves the field's source position. Catalogers can
            # add the explicit TASK-182 sort operation when canonical tag
            # order is required after structural changes.
            field.tag = request["destination_tag"]
            result["changed_fields"] += 1
            continue
        if request["action"] == "set_indicators":
            field.indicators = [request["new_ind1"], request["new_ind2"]]
            result["changed_fields"] += 1
            continue
        for index, subfield in enumerate(field.subfields):
            if request["target_kind"] == "subfield" and subfield.code != request.get("subfield"):
                continue
            new_value, count = matcher.subn(replacement, subfield.value, count=1 if request.get("occurrences") == "first" else 0)
            if count:
                field.subfields[index] = Subfield(subfield.code, new_value)
                result["matched_occurrences"] += count
                result["changed_fields"] += 1
    return result
