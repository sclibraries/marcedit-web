"""Pure helpers for structured Add Field and Build Field authoring."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, TypeVar

from pymarc import Record
from marcedit_web.lib.transforms import is_control_tag


EXISTING_FIELD_ACTIONS = (
    "append",
    "replace_all",
    "skip_if_tag_exists",
    "skip_if_identical",
)
MISSING_CONTROL_ACTIONS = ("skip_field", "fail_record")
_TAG_RE = re.compile(r"^\d{3}$")
_TOKEN_RE = re.compile(r"\{(\d{3})\}")
_T = TypeVar("_T")


def legacy_value_to_segments(value: str) -> list[dict[str, str]]:
    """Convert exact ``{NNN}`` legacy tokens to typed Build Field segments."""

    segments: list[dict[str, str]] = []
    offset = 0
    for match in _TOKEN_RE.finditer(value):
        if match.start() > offset:
            segments.append(
                {"type": "text", "value": value[offset:match.start()]}
            )
        segments.append({"type": "control_field", "tag": match.group(1)})
        offset = match.end()
    if offset < len(value):
        segments.append({"type": "text", "value": value[offset:]})
    consumed = "".join(
        segment["value"]
        if segment["type"] == "text"
        else "{" + segment["tag"] + "}"
        for segment in segments
    )
    if consumed != value or re.search(r"[{}]", _TOKEN_RE.sub("", value)):
        raise ValueError(
            "cannot convert legacy Build Field text losslessly; "
            "review literal braces and source references"
        )
    return segments or [{"type": "text", "value": ""}]


def move_item(
    items: Sequence[_T], index: int, direction: int
) -> list[_T]:
    """Return a copied sequence with one valid adjacent move applied."""

    result = copy.deepcopy(list(items))
    destination = index + direction
    if (
        index < 0
        or index >= len(result)
        or destination < 0
        or destination >= len(result)
    ):
        return result
    result[index], result[destination] = result[destination], result[index]
    return result


def normalize_operation(op: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an exact legacy Add/Build operation for structured editing."""

    normalized = copy.deepcopy(dict(op))
    params = normalized.setdefault("params", {})
    if normalized.get("kind") not in {"add-field", "build-field"}:
        return normalized
    params.setdefault(
        "existing_field_action",
        "skip_if_identical" if params.get("if_absent") else "append",
    )
    params.setdefault("missing_control_action", "skip_field")
    params.pop("if_absent", None)
    for name in ("ind1", "ind2"):
        if params.get(name) in ("", "\\", "\\\\"):
            params[name] = " "
    if (
        normalized["kind"] == "build-field"
        and "structured_subfields" not in params
    ):
        params["structured_subfields"] = [
            [str(code), legacy_value_to_segments(str(value))]
            for code, value in list(params.get("subfields") or [])
        ]
    if normalized["kind"] == "build-field":
        params.pop("subfields", None)
    return normalized


def normalize_operations_for_editor(
    ops: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize exact operations while retaining lossy legacy input visibly."""

    normalized = []
    for op in ops:
        original = copy.deepcopy(dict(op))
        try:
            normalized.append(normalize_operation(original))
        except ValueError as exc:
            original["authoring_error"] = str(exc)
            normalized.append(original)
    return normalized


_UNRESOLVED_ADD_BUILD_PREFIXES = (
    "# TODO: buildnewfield template ",
    "# TODO: unresolved ADD option(s);",
    "# TODO: ADD with unsupported condition ",
    "# TODO: malformed 'ADD' ",
    "# TODO: malformed 'buildnewfield' ",
)


def unresolved_add_build_instructions(body: str) -> tuple[str, ...]:
    """Return only unresolved Add/Build markers that block submission."""

    return tuple(
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith(_UNRESOLVED_ADD_BUILD_PREFIXES)
    )


def validate_operations(
    ops: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Validate operations and prefix errors with their one-based position."""

    errors = []
    for index, op in enumerate(ops):
        for error in validate_operation(op):
            errors.append("Operation {0}: {1}".format(index + 1, error))
    return tuple(errors)


def _validate_tag(tag: object) -> list[str]:
    value = str(tag or "")
    if not _TAG_RE.fullmatch(value):
        return ["tag must be exactly three numeric characters"]
    if value == "000" or is_control_tag(value):
        return ["Add Field and Build Field targets must be data fields"]
    return []


def _validate_indicator(value: object, label: str) -> list[str]:
    if len(str(value)) != 1:
        return [
            "{0} must be one character or an explicit blank".format(label)
        ]
    return []


def _validate_code(value: object, label: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9]", str(value or "")):
        return [
            "{0} must be one lowercase letter or digit".format(label)
        ]
    return []


def validate_operation(op: Mapping[str, Any]) -> tuple[str, ...]:
    """Return actionable validation errors for one structured operation."""

    kind = str(op.get("kind") or "")
    if kind not in {"add-field", "build-field"}:
        return ()
    try:
        normalized = normalize_operation(op)
    except ValueError as exc:
        return (str(exc),)
    params = normalized["params"]
    errors = _validate_tag(params.get("tag"))
    errors.extend(
        _validate_indicator(params.get("ind1", " "), "indicator 1")
    )
    errors.extend(
        _validate_indicator(params.get("ind2", " "), "indicator 2")
    )
    if params.get("existing_field_action") not in EXISTING_FIELD_ACTIONS:
        errors.append("existing-field action is not supported")
    if params.get("missing_control_action") not in MISSING_CONTROL_ACTIONS:
        errors.append("missing-control action is not supported")
    key = "subfields" if kind == "add-field" else "structured_subfields"
    subfields = list(params.get(key) or [])
    if not subfields:
        errors.append("at least one subfield is required")
        return tuple(errors)
    for subfield_index, subfield in enumerate(subfields, start=1):
        if not isinstance(subfield, (list, tuple)) or len(subfield) != 2:
            errors.append(
                "subfield {0} must contain a code and value".format(
                    subfield_index
                )
            )
            continue
        if str(subfield[0] or "") == "":
            errors.append(
                "Complete or remove blank subfield row {0}".format(
                    subfield_index
                )
            )
        else:
            errors.extend(
                _validate_code(
                    subfield[0],
                    "subfield {0} code".format(subfield_index),
                )
            )
        if kind == "add-field":
            if not isinstance(subfield[1], str):
                errors.append(
                    "subfield {0} value must be text".format(subfield_index)
                )
            continue
        segments = subfield[1]
        if not isinstance(segments, list) or not segments:
            errors.append(
                "subfield {0} needs at least one segment".format(
                    subfield_index
                )
            )
            continue
        if not any(
            isinstance(segment, Mapping)
            and (
                segment.get("type") == "control_field"
                or (
                    segment.get("type") == "text"
                    and bool(segment.get("value"))
                )
            )
            for segment in segments
        ):
            errors.append(
                "subfield {0} needs at least one output segment".format(
                    subfield_index
                )
            )
        for segment_index, segment in enumerate(segments, start=1):
            segment_type = (
                segment.get("type")
                if isinstance(segment, Mapping)
                else None
            )
            if segment_type == "text":
                if not isinstance(segment.get("value"), str):
                    errors.append(
                        "subfield {0} segment {1} literal must be "
                        "text".format(subfield_index, segment_index)
                    )
            elif segment_type == "control_field":
                tag = str(segment.get("tag") or "")
                if not is_control_tag(tag):
                    errors.append(
                        "subfield {0} segment {1} source must be control "
                        "field 001 through 009".format(
                            subfield_index, segment_index
                        )
                    )
            else:
                errors.append(
                    "subfield {0} segment {1} type is unsupported".format(
                        subfield_index, segment_index
                    )
                )
    return tuple(errors)


@dataclass(frozen=True)
class AuthoringPreview:
    """One deterministic, non-mutating structured-operation preview."""

    status: str
    mnemonic: str
    message: str


def _normalized_indicator(value: object) -> str:
    text = str(value or "")
    return " " if text in ("", "\\", "\\\\") else text


def _display_indicator(value: object) -> str:
    normalized = _normalized_indicator(value)
    return "\\" if normalized == " " else normalized


def _resolve_segments(
    segments: Sequence[Mapping[str, str]],
    record: Optional[Record],
) -> tuple[str, tuple[str, ...]]:
    parts = []
    missing = []
    for segment in segments:
        if segment["type"] == "text":
            parts.append(segment["value"])
            continue
        if record is None:
            parts.append("{" + segment["tag"] + "}")
            continue
        field = record.get(segment["tag"])
        if field is None:
            missing.append(segment["tag"])
        else:
            parts.append(str(field.data))
    return "".join(parts), tuple(dict.fromkeys(missing))


def _join_words(values: Sequence[str]) -> str:
    if len(values) < 2:
        return "".join(values)
    if len(values) == 2:
        return " and ".join(values)
    return ", ".join(values[:-1]) + ", and " + values[-1]


def _legacy_mnemonic(op: Mapping[str, Any]) -> str:
    params = dict(op.get("params") or {})
    prefix = "={0}  {1}{2}".format(
        params.get("tag", "???"),
        _display_indicator(params.get("ind1", " ")),
        _display_indicator(params.get("ind2", " ")),
    )
    return prefix + "".join(
        "${0}{1}".format(code, value)
        for code, value in list(params.get("subfields") or [])
    )


def describe_operation(op: Mapping[str, Any]) -> str:
    """Describe one Add/Build operation in cataloger-facing language."""

    try:
        normalized = normalize_operation(op)
    except ValueError as exc:
        return "Build Field needs review: {0}.".format(exc)
    params = normalized["params"]
    tag = params["tag"]
    article = "an" if tag.startswith(("0", "8")) else "a"
    ind1_value = _normalized_indicator(params.get("ind1", " "))
    ind2_value = _normalized_indicator(params.get("ind2", " "))
    ind1 = (
        "a blank indicator 1"
        if ind1_value == " "
        else "indicator 1 “{0}”".format(ind1_value)
    )
    ind2 = (
        "a blank indicator 2"
        if ind2_value == " "
        else "indicator 2 “{0}”".format(ind2_value)
    )
    if normalized["kind"] == "build-field":
        codes = [
            str(code)
            for code, _segments in params["structured_subfields"]
        ]
        label = "subfield" if len(codes) == 1 else "subfields"
        description = "Add {0} {1} field with {2}, {3}, and {4} {5}".format(
            article, tag, ind1, ind2, label, _join_words(codes)
        )
        sources = []
        for _code, segments in params["structured_subfields"]:
            for segment in segments:
                if (
                    segment["type"] == "control_field"
                    and segment["tag"] not in sources
                ):
                    sources.append(segment["tag"])
        if sources:
            description += " built from {0}".format(_join_words(sources))
    else:
        values = [
            "subfield {0} containing “{1}”".format(code, value)
            for code, value in params["subfields"]
        ]
        description = "Add {0} {1} field with {2}, {3}, and {4}".format(
            article, tag, ind1, ind2, _join_words(values)
        )
    existing = {
        "append": "add another field",
        "replace_all": "replace every field with this tag",
        "skip_if_tag_exists": "leave the record unchanged",
        "skip_if_identical": "add unless an identical field exists",
    }[params["existing_field_action"]]
    description += ". When {0} exists, {1}".format(tag, existing)
    if normalized["kind"] == "build-field":
        missing = {
            "skip_field": "do not build this field",
            "fail_record": "record a task error for this record",
        }[params["missing_control_action"]]
        description += ". If a source is missing, {0}".format(missing)
    return description + "."


def render_mnemonic(
    op: Mapping[str, Any],
    record: Optional[Record] = None,
) -> str:
    """Render transparent MARC mnemonic from structured values."""

    try:
        normalized = normalize_operation(op)
    except ValueError:
        return _legacy_mnemonic(op)
    params = normalized["params"]
    if normalized["kind"] == "add-field":
        resolved_subfields = [
            (str(code), str(value))
            for code, value in params["subfields"]
        ]
    else:
        resolved_subfields = [
            (str(code), _resolve_segments(segments, record)[0])
            for code, segments in params["structured_subfields"]
        ]
    prefix = "={0}  {1}{2}".format(
        params["tag"],
        _display_indicator(params.get("ind1", " ")),
        _display_indicator(params.get("ind2", " ")),
    )
    subfield_text = "".join(
        "${0}{1}".format(code, value)
        for code, value in resolved_subfields
    )
    return prefix + subfield_text


def token_annotations(op: Mapping[str, Any]) -> tuple[str, ...]:
    """Explain each displayed MARC token in order."""

    try:
        normalized = normalize_operation(op)
    except ValueError as exc:
        return (
            "Cannot interpret this legacy Build Field: {0}".format(exc),
            "Raw technical value preserved: {0}".format(
                _legacy_mnemonic(op)
            ),
        )
    params = normalized["params"]
    annotations = [
        "={0}: target MARC tag.".format(params["tag"]),
        "{0}{1}: indicator 1 and indicator 2; backslash means "
        "blank.".format(
            _display_indicator(params.get("ind1", " ")),
            _display_indicator(params.get("ind2", " ")),
        ),
    ]
    key = (
        "subfields"
        if normalized["kind"] == "add-field"
        else "structured_subfields"
    )
    for code, value in params[key]:
        annotations.append("${0}: start subfield {0}.".format(code))
        if normalized["kind"] == "add-field":
            annotations.append("{0}: literal subfield text.".format(value))
            continue
        for segment in value:
            if segment["type"] == "text":
                annotations.append(
                    "{0}: literal text.".format(segment["value"])
                )
            else:
                annotations.append(
                    "{{{0}}}: value from control field {0}.".format(
                        segment["tag"]
                    )
                )
    return tuple(annotations)


def preview_operation(
    op: Mapping[str, Any],
    record: Optional[Record],
) -> AuthoringPreview:
    """Preview one operation without mutating the loaded record."""

    errors = validate_operation(op)
    if errors:
        return AuthoringPreview("error", "", "; ".join(errors))
    normalized = normalize_operation(op)
    unresolved = render_mnemonic(normalized)
    if record is None:
        return AuthoringPreview(
            "no-file",
            unresolved,
            "Load a MARC file to resolve source control fields.",
        )
    candidate = copy.deepcopy(record)
    params = normalized["params"]
    missing = []
    if normalized["kind"] == "build-field":
        for _code, segments in params["structured_subfields"]:
            for segment in segments:
                if (
                    segment["type"] == "control_field"
                    and candidate.get(segment["tag"]) is None
                    and segment["tag"] not in missing
                ):
                    missing.append(segment["tag"])
    if missing:
        status = (
            "error"
            if params["missing_control_action"] == "fail_record"
            else "skipped"
        )
        return AuthoringPreview(
            status,
            unresolved,
            "Missing required control field {0}.".format(
                ", ".join(missing)
            ),
        )
    action = params["existing_field_action"]
    if action == "skip_if_tag_exists" and candidate.get_fields(params["tag"]):
        return AuthoringPreview(
            "skipped",
            unresolved,
            "Target field {0} already exists.".format(params["tag"]),
        )
    if action == "skip_if_identical":
        if normalized["kind"] == "add-field":
            signature_subfields = tuple(
                (str(code), str(value))
                for code, value in params["subfields"]
            )
        else:
            signature_subfields = tuple(
                (str(code), _resolve_segments(segments, candidate)[0])
                for code, segments in params["structured_subfields"]
            )
        new_signature = (
            _normalized_indicator(params.get("ind1", " ")),
            _normalized_indicator(params.get("ind2", " ")),
            signature_subfields,
        )
        existing_signatures = {
            (
                field.indicators[0],
                field.indicators[1],
                tuple((sf.code, sf.value) for sf in field.subfields),
            )
            for field in candidate.get_fields(params["tag"])
        }
        if new_signature in existing_signatures:
            return AuthoringPreview(
                "skipped",
                unresolved,
                "An identical {0} field already exists.".format(
                    params["tag"]
                ),
            )
    return AuthoringPreview(
        "ready",
        render_mnemonic(normalized, candidate),
        "Preview resolved from the first loaded record.",
    )
