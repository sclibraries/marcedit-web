"""Deterministic, bounded URL state for the Tasks workspace (TASK-193).

This module deliberately has no Streamlit or persistence dependency.  The
renderer owns authorization of task and folder IDs; this module only parses
the syntax that may safely be represented in a Tasks query string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Set, Union


QueryValue = Union[str, Sequence[str]]

TASK_QUERY_KEYS = frozenset(
    {
        "view",
        "mode",
        "scope",
        "folder",
        "q",
        "visibility",
        "owner",
        "tag",
        "subfield",
        "operation",
        "validation",
        "updated",
        "task",
        "dialog",
        "dialog_task",
        "dialog_folder",
    }
)

# These are the dialog modes currently rendered by ``render.tasks``.  The
# query parser intentionally does not resolve a target or check authorization.
_DIALOG_KINDS = frozenset(
    {
        "folder-create",
        "folder-rename",
        "folder-move",
        "folder-delete",
        "task-move",
        "task-share",
        "task-unshare",
    }
)

_POSITIVE_INTEGER = re.compile(r"^[0-9]+$")
_SUBFIELD = re.compile(r"^[A-Za-z0-9]$")


@dataclass(frozen=True)
class LibraryFilters:
    """Applied Library filters represented in the URL."""

    query: str = ""
    visibility: str = "all"
    owner: str = ""
    tag: str = ""
    subfield: str = ""
    operation: str = "all"
    validation: str = "all"
    updated: str = "any"


@dataclass(frozen=True)
class WorkspaceLocation:
    """The bounded Tasks navigation state.

    IDs are syntactically valid positive integers here.  Whether they are
    visible to the current cataloger is resolved by the renderer.
    """

    view: str = "run"
    mode: str = "saved"
    scope: str = "personal"
    folder_id: Optional[int] = None
    filters: LibraryFilters = LibraryFilters()
    task_id: Optional[int] = None
    dialog: Optional[str] = None
    dialog_task_id: Optional[int] = None
    dialog_folder_id: Optional[int] = None


def _scalar(raw: Mapping[str, QueryValue], key: str) -> Optional[str]:
    """Read one deterministic scalar from Streamlit's scalar/list values."""

    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        if not value:
            return None
        value = value[0]
    if value is None:
        return None
    return str(value)


def _bounded_text(
    raw: Mapping[str, QueryValue], key: str, *, maximum: int
) -> str:
    value = _scalar(raw, key)
    if value is None or len(value) > maximum:
        return ""
    return value


def _positive_id(raw: Mapping[str, QueryValue], key: str) -> Optional[int]:
    value = _scalar(raw, key)
    if value is None or not _POSITIVE_INTEGER.fullmatch(value):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _enum(
    raw: Mapping[str, QueryValue], key: str, *, allowed: Set[str], default: str
) -> str:
    value = _scalar(raw, key)
    return value if value in allowed else default


def parse_tasks_query(
    raw: Mapping[str, QueryValue], *, operation_kinds: Set[str]
) -> WorkspaceLocation:
    """Parse Tasks-owned query values, independently falling back on errors."""

    view = _enum(
        raw,
        "view",
        allowed={"run", "library", "create", "import"},
        default="run",
    )
    mode = _enum(raw, "mode", allowed={"saved", "quick"}, default="saved")
    scope = _enum(
        raw, "scope", allowed={"personal", "shared"}, default="personal"
    )
    visibility = _enum(
        raw,
        "visibility",
        allowed={"all", "private", "shared"},
        default="all",
    )
    validation = _enum(
        raw,
        "validation",
        allowed={"all", "valid", "legacy", "invalid"},
        default="all",
    )
    updated = _enum(raw, "updated", allowed={"any", "7", "30"}, default="any")

    operation = _scalar(raw, "operation")
    operation_set = set(operation_kinds)
    if operation != "all" and operation not in operation_set:
        operation = "all"
    if operation is not None and len(operation) > 64:
        operation = "all"
    if operation is None:
        operation = "all"

    subfield = _scalar(raw, "subfield")
    if subfield is None or subfield == "":
        subfield = ""
    elif not _SUBFIELD.fullmatch(subfield):
        subfield = ""

    dialog = _scalar(raw, "dialog")
    if dialog not in _DIALOG_KINDS:
        dialog = None

    return WorkspaceLocation(
        view=view,
        mode=mode,
        scope=scope,
        folder_id=_positive_id(raw, "folder"),
        filters=LibraryFilters(
            query=_bounded_text(raw, "q", maximum=255),
            visibility=visibility,
            owner=_bounded_text(raw, "owner", maximum=255),
            tag=_bounded_text(raw, "tag", maximum=3),
            subfield=subfield,
            operation=operation,
            validation=validation,
            updated=updated,
        ),
        task_id=_positive_id(raw, "task"),
        dialog=dialog,
        dialog_task_id=_positive_id(raw, "dialog_task"),
        dialog_folder_id=_positive_id(raw, "dialog_folder"),
    )


def canonical_tasks_query(location: WorkspaceLocation) -> dict[str, str]:
    """Serialize non-default Tasks state in stable query-key order."""

    result: dict[str, str] = {}
    if location.view != "run":
        result["view"] = location.view
    if location.mode != "saved":
        result["mode"] = location.mode
    if location.scope != "personal":
        result["scope"] = location.scope
    if location.folder_id is not None:
        result["folder"] = str(location.folder_id)

    filters = location.filters
    if filters.query:
        result["q"] = filters.query
    if filters.visibility != "all":
        result["visibility"] = filters.visibility
    if filters.owner:
        result["owner"] = filters.owner
    if filters.tag:
        result["tag"] = filters.tag
    if filters.subfield:
        result["subfield"] = filters.subfield
    if filters.operation != "all":
        result["operation"] = filters.operation
    if filters.validation != "all":
        result["validation"] = filters.validation
    if filters.updated != "any":
        result["updated"] = filters.updated

    if location.task_id is not None:
        result["task"] = str(location.task_id)
    if location.dialog is not None:
        result["dialog"] = location.dialog
    if location.dialog_task_id is not None:
        result["dialog_task"] = str(location.dialog_task_id)
    if location.dialog_folder_id is not None:
        result["dialog_folder"] = str(location.dialog_folder_id)
    return result


def merge_tasks_query(
    raw: Mapping[str, QueryValue], location: WorkspaceLocation
) -> dict[str, QueryValue]:
    """Replace Tasks-owned keys while preserving all other query values."""

    merged = {
        key: value for key, value in raw.items() if key not in TASK_QUERY_KEYS
    }
    merged.update(canonical_tasks_query(location))
    return merged

