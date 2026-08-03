"""Strict, dependency-light preflight for structured task markers."""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any, Mapping, Sequence


_OP_MARKER_CANDIDATE_RE = re.compile(r"^\s*#\s*OP:")
_OP_MARKER_RE = re.compile(
    r"^\s*#\s*OP:\s*(?P<kind>[a-z0-9-]+)\s*(?P<json>\{.*\})?\s*$"
)
_OPERATION_KIND_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_BLOCKER_PARAMS = {
    "intent",
    "reason",
    "suggestion",
    "instruction_sha256",
}
_SUGGESTION_PARAMS = {"operation_kind", "prefilled_params"}


def operation_markers(source: str) -> tuple[dict[str, Any], ...]:
    """Parse every present ``# OP:`` marker or fail closed."""

    operations = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if not _OP_MARKER_CANDIDATE_RE.match(line):
            continue
        match = _OP_MARKER_RE.match(line)
        if match is None:
            raise ValueError(_malformed_marker_message(line_number))
        raw_params = match.group("json") or "{}"
        try:
            params = json.loads(
                raw_params,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError):
            raise ValueError(_malformed_marker_message(line_number)) from None
        if not isinstance(params, Mapping):
            raise ValueError(_malformed_marker_message(line_number))
        operations.append(
            {
                "kind": match.group("kind"),
                "params": dict(params),
            }
        )
    return tuple(operations)


def migration_blockers(
    operations: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return copied structured migration blockers in source order."""

    return tuple(
        copy.deepcopy(dict(operation))
        for operation in operations
        if (
            isinstance(operation, Mapping)
            and operation.get("kind") == "migration-blocker"
        )
    )


def migration_blocker_errors(op: Mapping[str, Any]) -> tuple[str, ...]:
    """Return bounded validation errors for one blocker marker."""

    params = op.get("params")
    if not isinstance(params, Mapping):
        return ("operation parameters must be an object",)

    errors = []
    if any(not isinstance(key, str) for key in params):
        errors.append("migration blocker parameter keys must be text")
    unexpected_count = sum(
        not isinstance(key, str) or key not in _BLOCKER_PARAMS
        for key in params
    )
    if unexpected_count:
        errors.append(
            "migration blocker parameters contain {0} unexpected {1}".format(
                unexpected_count,
                "key" if unexpected_count == 1 else "keys",
            )
        )

    for name in ("intent", "reason"):
        value = params.get(name)
        if not isinstance(value, str):
            errors.append("{0} must be text".format(name))
        elif not " ".join(value.split()):
            errors.append("{0} is required".format(name))

    suggestion = params.get("suggestion")
    if not isinstance(suggestion, Mapping):
        errors.append("suggestion must be an object")
    else:
        if any(not isinstance(key, str) for key in suggestion):
            errors.append("suggestion keys must be text")
        unexpected_suggestion_count = sum(
            not isinstance(key, str) or key not in _SUGGESTION_PARAMS
            for key in suggestion
        )
        if unexpected_suggestion_count:
            errors.append(
                "suggestion contains {0} unexpected {1}".format(
                    unexpected_suggestion_count,
                    "key" if unexpected_suggestion_count == 1 else "keys",
                )
            )
        operation_kind = suggestion.get("operation_kind")
        if not isinstance(operation_kind, str):
            errors.append("suggested operation kind must be text")
        elif not operation_kind.strip():
            errors.append("suggested operation kind is required")
        elif _OPERATION_KIND_RE.fullmatch(operation_kind) is None:
            errors.append("suggested operation kind is invalid")
        prefilled = suggestion.get("prefilled_params")
        if not isinstance(prefilled, Mapping):
            errors.append("suggested prefilled parameters must be an object")
        elif not _is_safe_json_literal(prefilled):
            errors.append(
                "suggested prefilled parameters must use safe literals valid "
                "in JSON and mapping keys must be text"
            )

    digest = params.get("instruction_sha256")
    if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
        errors.append(
            "instruction digest must be 64 lowercase hexadecimal characters"
        )
    return tuple(errors)


def assert_runnable_operations(
    operations: Sequence[Mapping[str, Any]],
) -> None:
    """Reject invalid or unresolved structured migration blockers."""

    blockers = migration_blockers(operations)
    for blocker in blockers:
        errors = migration_blocker_errors(blocker)
        if errors:
            raise ValueError("Invalid migration blocker: {0}".format(errors[0]))
    if not blockers:
        return
    noun = "instruction" if len(blockers) == 1 else "instructions"
    raise ValueError(
        "Resolve {0} imported {1} before previewing or running this task."
        .format(len(blockers), noun)
    )


def assert_runnable_task_body(source: str) -> None:
    """Strictly parse markers and reject blockers before task execution."""

    assert_runnable_operations(operation_markers(source))


def _malformed_marker_message(line_number: int) -> str:
    return "Malformed operation marker on line {0}.".format(line_number)


def _unique_object(pairs) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("invalid JSON constant")


def _is_safe_json_literal(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_safe_json_literal(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _is_safe_json_literal(item)
            for key, item in value.items()
        )
    return False
