"""Safe, cataloger-oriented search over visible task metadata."""

from __future__ import annotations

import json
from typing import Any, Mapping

from . import native_tasks, task_preflight


def _walk_values(value: Any):
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_values(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _walk_values(nested)
    elif isinstance(value, (str, int, float, bool)):
        yield str(value)


def _operation_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    definition_json = row.get("definition_json")
    if definition_json:
        try:
            definition = native_tasks.load_definition_json(definition_json)
            operations = list(definition.get("steps", []))
        except (TypeError, ValueError, native_tasks.CompilerContractError):
            operations = []
    else:
        try:
            operations = [
                {"kind": op["kind"], "params": op.get("params", {})}
                for op in task_preflight.operation_markers(row.get("body", ""))
            ]
        except ValueError:
            operations = []
    kinds = [str(op.get("kind", "")) for op in operations if op.get("kind")]
    tags: set[str] = set()
    terms: list[str] = []
    for operation in operations:
        params = operation.get("params", {})
        if isinstance(params, Mapping):
            for key, value in params.items():
                if "tag" in str(key).lower() and isinstance(value, str):
                    tags.add(value)
            terms.extend(_walk_values(params))
    return {
        "operation_kinds": sorted(set(kinds)),
        "marc_tags": sorted(tags),
        "operation_terms": terms,
        "validation_state": "valid" if operations or definition_json else "legacy",
    }


def _safe_document(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _operation_metadata(row)
    searchable = " ".join(
        [
            str(row.get("name", "")),
            str(row.get("description", "")),
            str(row.get("owner_email", "")),
            str(row.get("visibility", "")),
            *metadata["operation_kinds"],
            *metadata["marc_tags"],
            *metadata["operation_terms"],
        ]
    ).casefold()
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "owner_email": row["owner_email"],
        "visibility": row["visibility"],
        "folder_id": row.get("folder_id"),
        "updated_at": row["updated_at"],
        **metadata,
        "_searchable": searchable,
    }


def search_visible_tasks(
    user: str,
    query: str = "",
    *,
    operation_kind: str | None = None,
    marc_tag: str | None = None,
    visibility: str | None = None,
) -> list[dict[str, Any]]:
    """Search only rows already authorized by ``task_db`` visibility rules."""
    from . import task_db

    documents = [_safe_document(row) for row in task_db.list_visible_tasks(user)]
    needle = str(query or "").casefold().strip()
    out = []
    for document in documents:
        if needle and needle not in document["_searchable"]:
            continue
        if operation_kind and operation_kind not in document["operation_kinds"]:
            continue
        if marc_tag and marc_tag not in document["marc_tags"]:
            continue
        if visibility and visibility != document["visibility"]:
            continue
        clean = {key: value for key, value in document.items() if key != "_searchable"}
        out.append(clean)
    return sorted(out, key=lambda row: (row["name"], row["id"]))

