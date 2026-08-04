"""Safe, cataloger-oriented search over visible task metadata."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from . import native_tasks, task_library, task_preflight


_TECHNICAL_KEYS = {
    "instruction_sha256",
    "fingerprint",
    "source_line",
    "source_format",
    "provenance",
}
_LITERAL_KEYS = {"find", "replacement", "value", "text", "literal"}
_SOURCE_KEYS = {"source_entry", "source_file", "imported_source"}


def _walk_values(value: Any):
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in _TECHNICAL_KEYS:
                continue
            yield str(key)
            yield from _walk_values(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _walk_values(nested)
    elif isinstance(value, (str, int, float, bool)):
        yield str(value)


def _collect_tags(value: Any) -> set[str]:
    tags: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if "tag" in str(key).lower() and isinstance(nested, str):
                tags.add(nested)
            tags.update(_collect_tags(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            tags.update(_collect_tags(nested))
    return tags


def _operation_content(value: Any) -> tuple[set[str], set[str]]:
    """Collect cataloger-facing subfield codes and literal values."""
    codes: set[str] = set()
    literals: set[str] = set()

    def walk(current: Any, key: str = "") -> None:
        if isinstance(current, Mapping):
            for child_key, child in current.items():
                name = str(child_key)
                if name in _TECHNICAL_KEYS:
                    continue
                if name in {"code", "subfield"} and isinstance(child, str):
                    if len(child) == 1 and child.isalnum():
                        codes.add(child)
                if name in _LITERAL_KEYS and isinstance(child, str):
                    literals.add(child)
                if name in _SOURCE_KEYS and isinstance(child, str):
                    # Source values are handled by the caller so this walker
                    # never mixes provenance into ordinary literals.
                    continue
                walk(child, name)
            return
        if isinstance(current, (list, tuple)):
            # Legacy/native subfield pairs are [code, value]. The first item
            # is a code; the second is cataloger-entered literal text.
            if key in {"subfields", "rows"}:
                for item in current:
                    if (
                        isinstance(item, (list, tuple))
                        and len(item) == 2
                        and isinstance(item[0], str)
                        and len(item[0]) == 1
                        and isinstance(item[1], str)
                    ):
                        codes.add(item[0])
                        literals.add(item[1])
            for child in current:
                walk(child, key)

    walk(value)
    return codes, literals


def _folder_paths(user: str) -> dict[int, str]:
    rows = task_library.list_folder_tree(user)
    by_id = {int(row["id"]): row for row in rows}
    paths: dict[int, str] = {}
    for folder_id, folder in by_id.items():
        names: list[str] = []
        current = folder_id
        seen: set[int] = set()
        while current in by_id and current not in seen:
            seen.add(current)
            current_row = by_id[current]
            names.append(str(current_row["name"]))
            parent = current_row.get("parent_id")
            current = int(parent) if parent is not None else -1
        scope_label = "Shared Tasks" if folder["scope"] == "shared" else "My Tasks"
        paths[folder_id] = " / ".join([scope_label, *reversed(names)])
    return paths


def _folder_descendant_ids(user: str, folder_id: int) -> set[int]:
    """Return a folder and all descendants visible to ``user``."""
    folders = task_library.list_folder_tree(user)
    children: dict[int | None, list[int]] = {}
    for folder in folders:
        parent = folder.get("parent_id")
        children.setdefault(int(parent) if parent is not None else None, []).append(
            int(folder["id"])
        )
    found: set[int] = set()
    pending = [int(folder_id)]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(children.get(current, []))
    return found


def _operation_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    native_definition = False
    parse_failed = False
    definition_json = row.get("definition_json")
    if definition_json:
        try:
            definition = native_tasks.load_definition_json(definition_json)
            native_definition = True
            operations = list(definition.get("steps", []))
        except (TypeError, ValueError, native_tasks.CompilerContractError):
            parse_failed = True
    else:
        try:
            operations = [
                {"kind": op["kind"], "params": op.get("params", {})}
                for op in task_preflight.operation_markers(row.get("body", ""))
            ]
        except ValueError:
            operations = []
    kinds = [
        str(op.get("kind") or op.get("action") or "")
        for op in operations
        if op.get("kind") or op.get("action")
    ]
    tags: set[str] = set()
    terms: list[str] = []
    subfield_codes: set[str] = set()
    literal_values: set[str] = set()
    imported_sources: set[str] = set()
    for operation in operations:
        params = operation.get("params", operation)
        if isinstance(params, Mapping):
            tags.update(_collect_tags(params))
            terms.extend(_walk_values(params))
            codes, literals = _operation_content(params)
            subfield_codes.update(codes)
            literal_values.update(literals)
            for key in _SOURCE_KEYS:
                value = params.get(key)
                if isinstance(value, str) and value:
                    imported_sources.add(value)
    description = str(row.get("description") or "")
    if description.casefold().startswith("imported from "):
        imported_sources.add(description[len("Imported from "):].strip())
    return {
        "operation_kinds": sorted(set(kinds)),
        "marc_tags": sorted(tags),
        "subfield_codes": sorted(subfield_codes),
        "literal_values": sorted(literal_values),
        "imported_sources": sorted(imported_sources),
        "operation_count": len(operations),
        "operation_terms": terms,
        "validation_state": (
            "invalid" if parse_failed
            else "valid" if native_definition
            else "legacy"
        ),
    }


def _safe_document(
    row: Mapping[str, Any],
    *,
    folder_path: str = "",
) -> dict[str, Any]:
    metadata = _operation_metadata(row)
    searchable = " ".join(
        [
            str(row.get("name", "")),
            str(row.get("description", "")),
            str(row.get("owner_email", "")),
            str(row.get("visibility", "")),
            folder_path,
            *metadata["operation_kinds"],
            *metadata["marc_tags"],
            *metadata["subfield_codes"],
            *metadata["literal_values"],
            *metadata["imported_sources"],
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
        "folder_path": folder_path,
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
    folder_id: int | None = None,
    owner: str | None = None,
    subfield_code: str | None = None,
    imported_source: str | None = None,
    validation_state: str | None = None,
    recent_days: int | None = None,
) -> list[dict[str, Any]]:
    """Search only rows already authorized by ``task_db`` visibility rules."""
    from . import task_db

    if recent_days is not None and recent_days <= 0:
        raise ValueError("recent_days must be positive")
    paths = _folder_paths(user)
    folder_ids = (
        _folder_descendant_ids(user, folder_id)
        if folder_id is not None else None
    )
    documents = [
        _safe_document(row, folder_path=paths.get(int(row["folder_id"]), ""))
        for row in task_db.list_visible_tasks(user)
    ]
    needle = str(query or "").casefold().strip()
    owner_needle = str(owner or "").casefold().strip()
    source_needle = str(imported_source or "").casefold().strip()
    recent_cutoff = None
    if recent_days is not None:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
    out = []
    for document in documents:
        if needle and needle not in document["_searchable"]:
            continue
        if operation_kind and str(operation_kind).casefold().replace("_", "-") not in {
            str(kind).casefold().replace("_", "-")
            for kind in document["operation_kinds"]
        }:
            continue
        if marc_tag and marc_tag not in document["marc_tags"]:
            continue
        if visibility and visibility != document["visibility"]:
            continue
        if folder_ids is not None and document["folder_id"] not in folder_ids:
            continue
        if owner_needle and owner_needle not in document["owner_email"].casefold():
            continue
        if (
            subfield_code
            and subfield_code not in document["subfield_codes"]
        ):
            continue
        if (
            source_needle
            and not any(source_needle in source.casefold()
                        for source in document["imported_sources"])
        ):
            continue
        if validation_state and validation_state != document["validation_state"]:
            continue
        if recent_cutoff is not None:
            try:
                updated = datetime.fromisoformat(
                    str(document["updated_at"]).replace("Z", "+00:00")
                )
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if updated < recent_cutoff:
                continue
        clean = {key: value for key, value in document.items() if key != "_searchable"}
        out.append(clean)
    return sorted(out, key=lambda row: (row["name"], row["id"]))
