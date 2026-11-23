"""Strict, dependency-light preflight for structured task markers."""

from __future__ import annotations

import copy
import io
import json
import math
import re
import tokenize
from typing import Any, Mapping, Sequence


ALLOWED_OPERATION_MARKER_KINDS = frozenset({
    "delete-tag",
    "delete-by-subfield",
    "delete-856-url-contains",
    "delete-856-url-regex",
    "add-field",
    "build-field",
    "subfield-replace",
    "guided-find-replace",
    "empty-find-subfield-policy",
    "copy-field",
    "copy-fields-with-policy",
    "build-fields-from-source",
    "institution-profile",
    "move-field",
    "add-subfield",
    "delete-subfield",
    "delete-subfield-if-value",
    "copy-subfield",
    "edit-indicators",
    "replace-field-data-by-regex",
    "replace-field-subfield-and-indicators",
    "sort-fields",
    "set-008-form",
    "rda-classify-material",
    "rda-mark-rda",
    "rda-remove-gmd",
    "rda-expand-abbreviations",
    "rda-normalize-relators",
    "rda-promote-260",
    "set-control-field",
    "structural-find-replace",
    "custom",
    "migration-blocker",
})
_OP_COMMENT_RE = re.compile(r"^#\s*OP:\s*(?P<body>.*)$")
_OP_BODY_RE = re.compile(
    r"^(?P<kind>[a-z0-9]+(?:-[a-z0-9]+)*)(?P<rest>.*)$"
)
_OPERATION_KIND_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_BLOCKER_PARAMS = {
    "intent",
    "reason",
    "cataloger_action",
    "suggestion",
    "instruction_sha256",
}
_SUGGESTION_PARAMS = {"operation_kind", "prefilled_params"}


def operation_markers(source: str) -> tuple[dict[str, Any], ...]:
    """Parse structured ``# OP:`` comment tokens or fail closed."""

    comments = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                comments.append((token.start[0], token.string))
    except (IndentationError, tokenize.TokenError):
        raise ValueError("Could not tokenize operation markers.") from None

    candidates = []
    for line_number, comment in comments:
        match = _OP_COMMENT_RE.match(comment)
        if match is None:
            continue
        body = match.group("body").strip()
        if not _is_structured_marker_candidate(body):
            continue
        candidates.append((line_number, body))

    operations = []
    for line_number, body in candidates:
        match = _OP_BODY_RE.match(body)
        if match is None:
            raise ValueError(_malformed_marker_message(line_number))
        raw_params = match.group("rest").strip() or "{}"
        if not raw_params.startswith("{"):
            raise ValueError(_malformed_marker_message(line_number))
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
        kind = match.group("kind")
        if kind not in ALLOWED_OPERATION_MARKER_KINDS:
            raise ValueError(
                "Unsupported operation marker kind on line {0}.".format(
                    line_number
                )
            )
        operations.append(
            {
                "kind": kind,
                "params": dict(params),
            }
        )
    return tuple(operations)


def _is_structured_marker_candidate(body: str) -> bool:
    if not body:
        return True
    match = _OP_BODY_RE.match(body)
    if match is None:
        return True
    kind = match.group("kind")
    rest = match.group("rest").strip()
    return (
        kind in ALLOWED_OPERATION_MARKER_KINDS
        or not rest
        or rest.startswith("{")
    )


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

    cataloger_action = params.get("cataloger_action")
    if cataloger_action is not None:
        if not isinstance(cataloger_action, str):
            errors.append("cataloger_action must be text")
        elif not " ".join(cataloger_action.split()):
            errors.append("cataloger_action is required when present")

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
    """Reject imported placeholders and unresolved migration blockers."""

    blockers = migration_blockers(operations)
    for blocker in blockers:
        errors = migration_blocker_errors(blocker)
        if errors:
            raise ValueError("Invalid migration blocker: {0}".format(errors[0]))
    if blockers:
        noun = "instruction" if len(blockers) == 1 else "instructions"
        raise ValueError(
            "Resolve {0} imported {1} before previewing or running this task."
            .format(len(blockers), noun)
        )

    placeholders = _untranslated_custom_placeholders(operations)
    if placeholders:
        noun = "instruction" if len(placeholders) == 1 else "instructions"
        shown = placeholders[:5]
        details = "; ".join(shown)
        remaining = len(placeholders) - len(shown)
        if remaining:
            details += "; {0} more".format(remaining)
        raise ValueError(
            "Resolve {0} untranslated MarcEdit {1} before previewing or "
            "running this task: {2}.".format(
                len(placeholders), noun, details
            )
        )


def _untranslated_custom_placeholders(
    operations: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return TODO texts from inert custom operations, in operation order."""

    placeholders = []
    for operation in operations:
        if (
            not isinstance(operation, Mapping)
            or operation.get("kind") != "custom"
        ):
            continue
        params = operation.get("params")
        if not isinstance(params, Mapping):
            continue
        code = params.get("code")
        if not isinstance(code, str):
            continue

        lines = code.splitlines()
        todo_texts = [
            line.lstrip()[len("# TODO:") :].strip()
            for line in lines
            if line.lstrip().startswith("# TODO:")
        ]
        if not todo_texts:
            continue
        if any(not _is_inert_custom_line(line) for line in lines):
            continue
        placeholders.append(todo_texts[0])
    return tuple(placeholders)


def _is_inert_custom_line(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or line.lstrip().startswith("#")
        or re.fullmatch(r"pass(?:\s*#.*)?", stripped) is not None
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
