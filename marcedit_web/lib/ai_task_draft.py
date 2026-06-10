"""Validate AI-authored task drafts before importing them into the editor."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from marcedit_web.lib import editor, task_builder


class DraftValidationError(ValueError):
    """Raised when the draft envelope is not usable JSON for review."""


@dataclass(frozen=True)
class DraftOperation:
    """One validated operation ready for the form editor."""

    kind: str
    params: dict[str, Any]
    source_text: str = ""
    explanation: str = ""
    confidence: str = ""
    regex: dict[str, str] | None = None


@dataclass(frozen=True)
class RejectedOperation:
    """One operation that could not be safely imported."""

    kind: str
    params: dict[str, Any]
    reason: str
    index: int | None = None
    source_text: str = ""


@dataclass(frozen=True)
class DraftReview:
    """Validated draft plus review items that need user attention."""

    task_name: str
    operations: tuple[DraftOperation, ...]
    rejected_operations: tuple[RejectedOperation, ...]
    questions: tuple[str, ...]
    manual_notes: tuple[str, ...]
    unsupported_lines: tuple[str, ...]
    description: str = ""


_PALETTE_BY_KIND = {op["kind"]: op for op in task_builder.OPERATIONS_PALETTE}
_STRING_TYPES = {"text", "indicator", "subfield_code", "code"}
_REGEX_PARAMS_BY_KIND = {
    "replace-field-data-by-regex": ("pattern",),
    "delete-856-url-regex": ("pattern",),
}
_UNSUPPORTED_AI_OPERATION_KINDS = {"custom"}
_CODE_SHAPED_RE = re.compile(
    r"(__import__|\bimport\b|\bfrom\s+\S+\s+import\b|\bexec\s*\(|"
    r"\beval\s*\(|\bopen\s*\(|\brecord\.[A-Za-z_]\w*\s*\(|"
    r"\bos\.|\bsubprocess\b|\bsys\.|\bPath\s*\()"
)


def parse_ai_task_draft(raw_text: str) -> DraftReview:
    """Parse and validate a JSON task draft produced by AI assistance."""

    data = _parse_json_object(raw_text)
    task_name = data.get("task_name")
    if not isinstance(task_name, str) or not editor.is_valid_slug(task_name):
        raise DraftValidationError("task_name must be a valid task slug")

    raw_operations = data.get("operations", [])
    if not isinstance(raw_operations, list):
        raise DraftValidationError("operations must be a list")

    operations: list[DraftOperation] = []
    rejected: list[RejectedOperation] = []
    for index, raw_op in enumerate(raw_operations):
        result = _validate_operation(raw_op, index)
        if isinstance(result, DraftOperation):
            operations.append(result)
        else:
            rejected.append(result)

    return DraftReview(
        task_name=task_name,
        operations=tuple(operations),
        rejected_operations=tuple(rejected),
        questions=_string_tuple(data, "questions"),
        manual_notes=_string_tuple(data, "manual_notes"),
        unsupported_lines=_string_tuple(data, "unsupported_lines"),
        description=_optional_string(data, "description"),
    )


def operations_for_editor(review: DraftReview) -> list[dict]:
    """Return validated operations in the form-builder JSON shape."""

    return [
        {"kind": op.kind, "params": _copy_jsonish(op.params)}
        for op in review.operations
    ]


def blocking_issue_count(review: DraftReview) -> int:
    """Count review issues that should block saving without user attention."""

    return (
        len(review.rejected_operations)
        + len(review.questions)
        + len(review.unsupported_lines)
    )


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    if not stripped.startswith("{"):
        raise DraftValidationError("draft response must be a JSON object")
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise DraftValidationError(f"draft response must be valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DraftValidationError("draft response must be a JSON object")
    return data


def _validate_operation(raw_op: Any, index: int) -> DraftOperation | RejectedOperation:
    if not isinstance(raw_op, dict):
        return RejectedOperation("", {}, "operation must be an object", index)

    kind = raw_op.get("kind")
    params = raw_op.get("params", {})
    source_text = _optional_string(raw_op, "source_text")
    explanation = _optional_string(raw_op, "explanation")
    confidence = _optional_string(raw_op, "confidence")
    regex_metadata = _optional_string_dict(raw_op, "regex")
    if not isinstance(kind, str) or not kind:
        return RejectedOperation(
            "",
            _dict_or_empty(params),
            "operation kind is required",
            index,
            source_text,
        )
    if not isinstance(params, dict):
        return RejectedOperation(kind, {}, "params must be an object", index, source_text)
    if regex_metadata == "invalid":
        return RejectedOperation(
            kind,
            dict(params),
            "regex must be an object with string values",
            index,
            source_text,
        )

    palette_op = _PALETTE_BY_KIND.get(kind)
    if palette_op is None:
        return RejectedOperation(
            kind,
            dict(params),
            f"unknown operation kind '{kind}'",
            index,
            source_text,
        )
    if kind in _UNSUPPORTED_AI_OPERATION_KINDS:
        return RejectedOperation(
            kind,
            dict(params),
            f"{kind} operations are not supported in AI drafts",
            index,
            source_text,
        )

    param_specs = {param["name"]: param for param in palette_op["params"]}
    for name in params:
        if name not in param_specs:
            return RejectedOperation(
                kind,
                dict(params),
                f"unknown param '{name}'",
                index,
                source_text,
            )

    for name, spec in param_specs.items():
        if spec.get("required") and _is_empty(params.get(name)):
            return RejectedOperation(
                kind,
                dict(params),
                f"required param '{name}' is missing",
                index,
                source_text,
            )

    for name, value in params.items():
        reason = _param_type_error(name, value, param_specs[name])
        if reason is not None:
            return RejectedOperation(kind, dict(params), reason, index, source_text)
        if _contains_code_shaped_value(value):
            return RejectedOperation(
                kind,
                dict(params),
                f"param '{name}' contains code-shaped value",
                index,
                source_text,
            )

    regex_error = _regex_error(kind, params)
    if regex_error is not None:
        return RejectedOperation(kind, dict(params), regex_error, index, source_text)

    return DraftOperation(
        kind=kind,
        params=_copy_jsonish(params),
        source_text=source_text,
        explanation=explanation,
        confidence=confidence,
        regex=_copy_jsonish(regex_metadata) if regex_metadata is not None else None,
    )


def _param_type_error(name: str, value: Any, spec: dict) -> str | None:
    param_type = spec.get("type")
    if param_type in _STRING_TYPES:
        if not isinstance(value, str):
            return f"param '{name}' must be a string"
        return None
    if param_type == "select":
        if not isinstance(value, str):
            return f"param '{name}' must be a string"
        option_values = _select_option_values(spec)
        if option_values and value not in option_values:
            return f"param '{name}' must be one of: {', '.join(option_values)}"
        return None
    if param_type == "bool":
        if not isinstance(value, bool):
            return f"param '{name}' must be a boolean"
        return None
    if param_type == "subfields":
        expected = (
            f"param '{name}' must be a list of [code, value] pairs, "
            'e.g. [["a", "Electronic scores."], ["2", "local"]]'
        )
        if not isinstance(value, list):
            return expected
        for item in value:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], str)
            ):
                return expected
    return None


def _select_option_values(spec: dict) -> list[str]:
    values: list[str] = []
    for option in spec.get("options", []):
        if isinstance(option, dict) and isinstance(option.get("value"), str):
            values.append(option["value"])
    return values


def _regex_error(kind: str, params: dict[str, Any]) -> str | None:
    regex_param_names = _REGEX_PARAMS_BY_KIND.get(kind, ())
    if kind == "subfield-replace" and params.get("regex") is True:
        regex_param_names = ("find",)

    for name in regex_param_names:
        pattern = params.get(name)
        if not isinstance(pattern, str):
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"invalid regex in param '{name}': {exc}"
    return None


def _string_tuple(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DraftValidationError(f"{key} must be a list of strings")
    return tuple(value)


def _optional_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DraftValidationError(f"{key} must be a string")
    return value


def _optional_string_dict(data: dict[str, Any], key: str) -> dict[str, str] | str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        return "invalid"
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        return "invalid"
    return dict(value)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


def _contains_code_shaped_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_CODE_SHAPED_RE.search(value))
    if isinstance(value, list):
        return any(_contains_code_shaped_value(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_code_shaped_value(item) for item in value.values())
    return False


def _copy_jsonish(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}
