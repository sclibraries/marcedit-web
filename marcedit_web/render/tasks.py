"""Tasks tab — list / create / import / run tasks against the loaded batch.

v3 changes:
* Default users see only the **form builder**. The Code view is gated
  to admins via :func:`task_admin.is_admin` (env: ``MARCEDIT_WEB_ADMINS``).
* Saved-task runs execute synchronously through the subprocess sandbox. The
  production hotfix deliberately leaves durable Operations and its worker
  out of the user-facing run path.
* Task files keep round-tripping through the existing
  ``editor.parse_user_task_file`` / ``task_builder.parse_ops_from_source``
  / ``task_builder.render_ops_to_python`` plumbing. Form-built tasks
  carry ``# OP:`` markers so re-opening them returns to form view.

TASK-050: tasks are stored in the SQLite ``tasks`` table with a
private/shared visibility flag. Files on disk are still the
loader's contract; ``task_db.materialize_to_dir`` writes each
visible task to a per-session ``/tmp/marcedit-web-tasks-<sid>/``
on every render. Save / delete / visibility writes go to SQL.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
import pymarc
import streamlit as st
from streamlit_ace import st_ace

from marcedit_web.lib import (
    ai_task_draft,
    batch_runtime,
    batch_replace,
    collaboration,
    editor,
    external_task_migration,
    gemini_task_draft,
    guided_replace_preview,
    job_files,
    marcedit_import,
    native_tasks,
    note_task_draft,
    operation_submission,
    quotas,
    quick_batch,
    rda_operations,
    sandbox,
    synchronous_task_runner,
    session,
    snapshot_actions,
    task_admin,
    task_authoring,
    task_builder,
    task_db,
    task_diff,
    task_library,
    task_library_search,
    tasks,
)
from marcedit_web.lib.audit import audit_event
from marcedit_web.lib.batch_replace import BatchReplaceRequest
from marcedit_web.lib.quick_batch import QuickBatchRequest
from marcedit_web.lib.record_store import RecordStore
from marcedit_web.lib.task_builder import OPERATIONS_PALETTE, Operation
from marcedit_web.lib.task_workspace_navigation import (
    WorkspaceLocation,
    canonical_tasks_query,
    merge_tasks_query,
    parse_tasks_query,
)
from marcedit_web.render.batch_status import loaded_batch_status
from marcedit_web.render import task_authoring as task_authoring_render
from marcedit_web.render import (
    task_operation_cards,
    task_operation_dialog,
    task_operation_reference,
)

logger = logging.getLogger("marcedit_web.render.tasks")


@contextmanager
def _batch_operation(operation: str, *, phase: str, store):
    """Apply the shared gate and consistent dimensions to heavy work."""
    try:
        file_bytes = store.path.stat().st_size
    except OSError:
        file_bytes = 0
    with batch_runtime.batch_slot(operation):
        with batch_runtime.measure_operation(
            operation,
            phase=phase,
            records=store.count(),
            bytes=file_bytes,
        ) as measurement:
            yield measurement


def _uses_job_file_versions() -> bool:
    return st.session_state.get("job_file_id") is not None


@contextmanager
def _owned_candidate(source_path: Path, *, prefix: str):
    workdir = Path(tempfile.mkdtemp(prefix=prefix))
    candidate_path = workdir / "candidate.mrc"
    try:
        shutil.copyfile(source_path, candidate_path)
        yield candidate_path
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Session-state keys (Stage 22)
#
# Single source of truth for every ``tasks_*`` key the editor flow writes
# into ``st.session_state``. A typo at a callsite now becomes an
# ImportError / AttributeError instead of a silent state-leak bug where
# the editor reads from one key and writes to another. Widget ``key=``
# arguments use the same constants so a future rename is one find.
# ---------------------------------------------------------------------------

K_EDITOR_OPEN = "tasks_editor_open"
K_EDITOR_MODE = "tasks_editor_mode"
K_EDITOR_NAME = "tasks_editor_name"
K_EDITOR_DESCRIPTION = "tasks_editor_description"
K_EDITOR_BODY = "tasks_editor_body"
K_EDITOR_OPS = "tasks_editor_ops"
K_EDITOR_ORIGINAL_NAME = "tasks_editor_original_name"
K_EDITOR_ORIGINAL_OWNER = "tasks_editor_original_owner"
K_EDITOR_PRESERVE_BODY = "tasks_editor_preserve_body"
K_EDITOR_VISIBILITY = "tasks_editor_visibility"
K_EDITOR_NAME_INPUT = "tasks_editor_name_input"
K_EDITOR_DESCRIPTION_INPUT = "tasks_editor_description_input"
K_EDITOR_FROM_AI_DRAFT = "tasks_editor_from_ai_draft"
K_EDITOR_AI_DRAFT_REVIEW = "tasks_editor_ai_draft_review"
K_EDITOR_IMPORT_SUMMARY = "tasks_editor_import_summary"
K_EDITOR_IMPORT_PROVENANCE = "tasks_editor_import_provenance"
K_EDITOR_IMPORT_DISCLOSURES = "tasks_editor_import_disclosures"
K_EDITOR_IMPORT_SOURCE = "tasks_editor_import_source"
K_LIBRARY_FOLDER_ID = "tasks_library_folder_id"
K_LIBRARY_SCOPE = "tasks_library_scope"
K_LIBRARY_QUERY = "tasks_library_query"
K_LIBRARY_VISIBILITY = "tasks_library_visibility"
K_LIBRARY_OWNER = "tasks_library_owner"
K_LIBRARY_KIND = "tasks_library_kind"
K_LIBRARY_TAG = "tasks_library_tag"
K_LIBRARY_SUBFIELD = "tasks_library_subfield"
K_LIBRARY_VALIDATION = "tasks_library_validation"
K_LIBRARY_RECENT = "tasks_library_recent"
K_LIBRARY_DIALOG = "tasks_library_dialog"
K_LIBRARY_DIALOG_FOLDER = "tasks_library_dialog_folder"
K_LIBRARY_DIALOG_TASK = "tasks_library_dialog_task"
K_SAVE_ERROR = "tasks_save_error"
K_SAVE_SUCCESS = "tasks_save_success"
K_MATERIALIZED_DIR = "tasks_materialized_dir"
K_AI_DRAFT_NOTES = "tasks_ai_draft_notes"
K_AI_DRAFT_REVIEW = "tasks_ai_draft_review"
K_AI_DRAFT_ERROR = "tasks_ai_draft_error"
K_AI_DRAFT_BLOCKING_ACK = "tasks_ai_draft_blocking_ack"
K_MARCEDIT_IMPORT_RESULT = "tasks_marcedit_import_result"
K_MARCEDIT_IMPORT_ADOPTED_ENTRY = "tasks_marcedit_import_adopted_entry"
K_QB_DOWNLOAD_READY = "quick_batch_download_ready"
K_GUIDED_REPLACE_PREVIEWS = "task_guided_replace_previews"
K_OPERATION_DIALOG_STATE = "tasks_operation_dialog_state"
K_OPERATION_DIALOG_NONCE = "tasks_operation_dialog_nonce"
K_OPERATION_REFERENCE_REQUESTED = "tasks_operation_reference_requested"
K_OPERATION_CARDS_PENDING_REMOVE = "task_operation_cards_pending_remove"
K_SYNC_RUN_RESULT = "tasks_sync_run_result"

# Retained draft bounds follow the existing archive envelope: ZIP entry names
# are at most 65,535 bytes and an archive may expand to 50 MiB. The shortest
# retained instruction occupies two bytes including its newline.
MAX_DRAFT_PROVENANCE_ITEMS = (50 * 1024 * 1024) // 2
MAX_DRAFT_SOURCE_ENTRY_BYTES = 65_535
MAX_DRAFT_SOURCE_LINE_BYTES = 50 * 1024 * 1024
MAX_DRAFT_OPERATIONS = 10_000
MAX_DRAFT_DISCLOSURES = len(external_task_migration.ADAPTER_REGISTRY)
MAX_DRAFT_DISCLOSURE_CHARS = 1_024
MAX_DRAFT_TASK_NAME_CHARS = 255

# TASK-193: URL-owned workspace navigation. Draft and import values remain
# non-widget session state so Streamlit may safely clean up disappearing
# widgets during a query-only page transition.
WORKSPACE_VIEWS = {
    "run": "Run",
    "library": "Library",
    "create": "Create",
    "import": "Import",
}
RUN_MODES = {"saved": "Saved tasks", "quick": "Quick changes"}
K_WORKSPACE_LOCATION = "tasks_workspace_location"
K_WORKSPACE_OWN_WRITE = "tasks_workspace_own_write"
K_WORKSPACE_VIEW_WIDGET = "tasks_workspace_view"
K_RUN_MODE_WIDGET = "tasks_run_mode"


def _materialized_dir(user: str) -> Path:
    """Per-session tmp dir holding the user's visible tasks as .py files.

    Created lazily once per Streamlit session. The dir is re-populated
    on every page render by ``task_db.materialize_to_dir`` — cheap,
    because that helper only rewrites files whose content changed.

    Lifecycle: tied to ``st.session_state``; reclaimed when the
    session ends (the OS cleans ``/tmp`` on container restart, and a
    long-lived container can be swept via the standard ``find /tmp
    -name 'marcedit-web-*' -mtime +2`` cron documented in deployment.md).
    """
    if K_MATERIALIZED_DIR not in st.session_state:
        sid = uuid.uuid4().hex[:8]
        st.session_state[K_MATERIALIZED_DIR] = (
            Path(tempfile.gettempdir()) / f"marcedit-web-tasks-{sid}"
        )
    target = st.session_state[K_MATERIALIZED_DIR]
    target.mkdir(parents=True, exist_ok=True)
    return target


def _refresh_tasks_for(user: str) -> Path:
    """Materialize visible tasks for ``user`` and return the dir.

    Call this before reading the task registry. Idempotent.
    """
    target = _materialized_dir(user)
    task_db.materialize_to_dir(user, target)
    return target


def _workspace_operation_kinds() -> set[str]:
    return {
        str(entry["kind"])
        for entry in OPERATIONS_PALETTE
        if isinstance(entry, dict) and entry.get("kind")
    }


def _complete_query_mapping() -> dict[str, object]:
    """Return query parameters, retaining repeated non-Tasks values."""
    if not hasattr(st, "query_params"):
        return {}
    query = st.query_params
    keys = list(query.keys()) if hasattr(query, "keys") else []
    result: dict[str, object] = {}
    for key in keys:
        if hasattr(query, "get_all"):
            values = list(query.get_all(key))
            if len(values) > 1:
                result[key] = values
            elif values:
                result[key] = values[0]
        else:
            result[key] = query[key]
    return result


def _read_workspace_location() -> WorkspaceLocation:
    return parse_tasks_query(
        _complete_query_mapping(),
        operation_kinds=_workspace_operation_kinds(),
    )


def _write_workspace_location(location: WorkspaceLocation) -> None:
    merged = merge_tasks_query(_complete_query_mapping(), location)
    st.session_state[K_WORKSPACE_LOCATION] = location
    st.session_state[K_WORKSPACE_OWN_WRITE] = canonical_tasks_query(location)
    if hasattr(st, "query_params"):
        st.query_params.from_dict(merged)


def _select_workspace(view: str, **changes: object) -> None:
    current = st.session_state.get(K_WORKSPACE_LOCATION, WorkspaceLocation())
    _write_workspace_location(dataclasses.replace(current, view=view, **changes))
    st.rerun()


def _authorized_workspace_location(
    location: WorkspaceLocation,
    *,
    visible_task_ids: set[int],
    visible_folder_ids: set[int],
) -> WorkspaceLocation:
    target_ids = (location.task_id, location.folder_id)
    dialog_target_ids = (location.dialog_task_id, location.dialog_folder_id)
    if any(
        target is not None and target not in visible
        for target, visible in zip(
            target_ids + dialog_target_ids,
            (visible_task_ids, visible_folder_ids) * 2,
        )
    ):
        return dataclasses.replace(
            location,
            view="library",
            task_id=None,
            folder_id=None,
            dialog=None,
            dialog_task_id=None,
            dialog_folder_id=None,
        )
    return location


def _apply_workspace_location(location: WorkspaceLocation) -> None:
    st.session_state[K_WORKSPACE_LOCATION] = location
    # These selectors are widgets, but their values are URL projections. An
    # external query-only rerun must discard the previous widget value before
    # Streamlit instantiates the control again; otherwise a stale Run/Quick
    # selection can overwrite the externally requested Library/Saved URL.
    st.session_state.pop(K_WORKSPACE_VIEW_WIDGET, None)
    st.session_state.pop(K_RUN_MODE_WIDGET, None)
    st.session_state[K_LIBRARY_SCOPE] = location.scope
    st.session_state[K_LIBRARY_FOLDER_ID] = location.folder_id
    filters = location.filters
    st.session_state[K_LIBRARY_QUERY] = filters.query
    st.session_state[K_LIBRARY_VISIBILITY] = filters.visibility
    st.session_state[K_LIBRARY_OWNER] = filters.owner
    st.session_state[K_LIBRARY_TAG] = filters.tag
    st.session_state[K_LIBRARY_SUBFIELD] = filters.subfield
    st.session_state[K_LIBRARY_KIND] = filters.operation
    st.session_state[K_LIBRARY_VALIDATION] = filters.validation
    st.session_state[K_LIBRARY_RECENT] = filters.updated
    st.session_state[K_LIBRARY_DIALOG] = location.dialog
    st.session_state[K_LIBRARY_DIALOG_TASK] = location.dialog_task_id
    st.session_state[K_LIBRARY_DIALOG_FOLDER] = location.dialog_folder_id


def _sync_workspace_from_url(
    location: WorkspaceLocation,
    visible_task_ids: set[int],
    visible_folder_ids: set[int],
) -> WorkspaceLocation:
    """Apply URL navigation while retaining non-widget drafts."""
    resolved = _authorized_workspace_location(
        location,
        visible_task_ids=visible_task_ids,
        visible_folder_ids=visible_folder_ids,
    )
    own_write = st.session_state.get(K_WORKSPACE_OWN_WRITE)
    if own_write == canonical_tasks_query(location):
        st.session_state.pop(K_WORKSPACE_OWN_WRITE, None)
        if own_write == canonical_tasks_query(resolved):
            return resolved
    elif (
        K_WORKSPACE_LOCATION in st.session_state
        and canonical_tasks_query(st.session_state[K_WORKSPACE_LOCATION])
        == canonical_tasks_query(resolved)
    ):
        return resolved
    _apply_workspace_location(resolved)
    return resolved


def render() -> None:
    """Render the Tasks tab into the current Streamlit container."""
    current_user_id = session.current_user_id()
    is_admin = task_admin.is_admin(current_user_id)
    tasks_dir = _refresh_tasks_for(current_user_id)

    # Editor draft state — namespaced.
    st.session_state.setdefault(K_EDITOR_OPEN, False)
    st.session_state.setdefault(K_EDITOR_MODE, "form")  # "form" | "code"
    st.session_state.setdefault(K_EDITOR_NAME, "")
    st.session_state.setdefault(K_EDITOR_DESCRIPTION, "")
    st.session_state.setdefault(K_EDITOR_BODY, "")
    st.session_state.setdefault(K_EDITOR_OPS, [])  # list[dict] — Operation.to_dict()
    st.session_state.setdefault(K_EDITOR_ORIGINAL_NAME, None)
    st.session_state.setdefault(K_EDITOR_ORIGINAL_OWNER, None)
    st.session_state.setdefault(K_EDITOR_PRESERVE_BODY, False)
    st.session_state.setdefault(K_EDITOR_VISIBILITY, "private")
    st.session_state.setdefault(K_LIBRARY_FOLDER_ID, None)
    st.session_state.setdefault(K_LIBRARY_SCOPE, "all")
    st.session_state.setdefault(K_LIBRARY_QUERY, "")
    st.session_state.setdefault(K_LIBRARY_VISIBILITY, "all")
    st.session_state.setdefault(K_LIBRARY_OWNER, "")
    st.session_state.setdefault(K_LIBRARY_KIND, "all")
    st.session_state.setdefault(K_LIBRARY_TAG, "")
    st.session_state.setdefault(K_LIBRARY_SUBFIELD, "")
    st.session_state.setdefault(K_LIBRARY_VALIDATION, "all")
    st.session_state.setdefault(K_LIBRARY_RECENT, "any")
    st.session_state.setdefault(K_LIBRARY_DIALOG, None)
    st.session_state.setdefault(K_EDITOR_FROM_AI_DRAFT, False)
    st.session_state.setdefault(K_EDITOR_AI_DRAFT_REVIEW, None)
    st.session_state.setdefault(K_OPERATION_DIALOG_STATE, None)
    st.session_state.setdefault(K_OPERATION_DIALOG_NONCE, 0)
    st.session_state.setdefault(K_OPERATION_REFERENCE_REQUESTED, False)
    st.session_state.setdefault(K_MARCEDIT_IMPORT_RESULT, None)
    st.session_state.setdefault(K_MARCEDIT_IMPORT_ADOPTED_ENTRY, None)
    st.session_state.setdefault(K_SYNC_RUN_RESULT, None)
    st.session_state.setdefault(K_WORKSPACE_LOCATION, WorkspaceLocation())

    # Load the materialized dir so the importer sees the user's tasks.
    tasks.load_user_tasks(tasks_dir, force_reload=False)
    registered = tasks.all_tasks()

    loaded_batch_status()

    try:
        visible_tasks = task_db.list_visible_tasks(current_user_id)
        visible_task_ids = {int(row["id"]) for row in visible_tasks}
    except (KeyError, TypeError, ValueError, sqlite3.OperationalError):
        visible_task_ids = set()
    try:
        visible_folders = task_library.list_folder_tree(current_user_id)
        visible_folder_ids = {int(folder["id"]) for folder in visible_folders}
    except (KeyError, TypeError, ValueError, sqlite3.OperationalError):
        visible_folder_ids = set()
    location = _sync_workspace_from_url(
        _read_workspace_location(), visible_task_ids, visible_folder_ids
    )
    view_label = st.segmented_control(
        "Tasks workspace",
        options=list(WORKSPACE_VIEWS.values()),
        default=WORKSPACE_VIEWS[location.view],
        key=K_WORKSPACE_VIEW_WIDGET,
        label_visibility="collapsed",
    )
    selected_view = next(
        (value for value, label in WORKSPACE_VIEWS.items() if label == view_label),
        location.view,
    )
    if selected_view != location.view:
        _select_workspace(selected_view)
        return
    st.divider()

    if location.view == "run":
        mode_label = st.segmented_control(
            "Run mode",
            options=list(RUN_MODES.values()),
            default=RUN_MODES[location.mode],
            key=K_RUN_MODE_WIDGET,
            label_visibility="collapsed",
        )
        selected_mode = next(
            (value for value, label in RUN_MODES.items() if label == mode_label),
            location.mode,
        )
        if selected_mode != location.mode:
            _select_workspace("run", mode=selected_mode)
            return
        if location.mode == "quick":
            _render_quick_ops_mode()
        else:
            _render_saved_tasks(registered, tasks_dir)
    elif location.view == "library":
        _render_task_library(current_user_id=current_user_id, is_admin=is_admin)
    elif location.view == "create":
        _render_create_workspace(tasks_dir, is_admin, current_user_id, registered)
    else:
        _render_import_workspace(tasks_dir, current_user_id, registered)


def _normalize_marcedit_import_result(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    status = value.get("status")
    if status not in {"success", "partial", "rejected"}:
        return {}
    if "uploaded_filename" not in value:
        return {}
    if not isinstance(value.get("imported_task_names"), list):
        return {}
    if not isinstance(value.get("entries"), list):
        return {}

    def safe_text_list(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(item)[:1024] for item in raw if isinstance(item, str)]

    def safe_migration_items(raw: object) -> list[dict]:
        if not isinstance(raw, list):
            return []
        normalized: list[dict] = []
        for item in raw[:20]:
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            if status not in {"converted", "choice_required", "unresolved"}:
                continue
            normalized.append({
                "status": status,
                "source_line": str(item.get("source_line") or "")[:2048],
                "reason": str(item.get("reason") or "")[:1024],
                "cataloger_action": str(
                    item.get("cataloger_action") or ""
                )[:2048],
                "choices": safe_text_list(item.get("choices"))[:8],
                "instruction_sha256": str(
                    item.get("instruction_sha256") or ""
                )[:64],
                "operation": (
                    copy.deepcopy(item.get("operation"))
                    if isinstance(item.get("operation"), dict)
                    else None
                ),
            })
        return normalized

    def safe_draft(
        raw: object,
        *,
        entry_name: str,
        entry_status: str,
        entry_task_name: str | None,
    ) -> dict | None:
        if not isinstance(raw, dict):
            return None
        operations = raw.get("operations")
        summary = raw.get("summary")
        provenance_value = raw.get("provenance")
        disclosures_value = raw.get("disclosures")
        task_name = raw.get("task_name")
        description = raw.get("description")
        if (
            not isinstance(operations, list)
            or not isinstance(summary, dict)
            or not isinstance(provenance_value, list)
            or len(provenance_value) > MAX_DRAFT_PROVENANCE_ITEMS
            or not isinstance(disclosures_value, list)
            or len(disclosures_value) > MAX_DRAFT_DISCLOSURES
            or not all(
                isinstance(item, str)
                and len(item) <= MAX_DRAFT_DISCLOSURE_CHARS
                for item in disclosures_value
            )
            or len(operations) > MAX_DRAFT_OPERATIONS
            or not isinstance(task_name, str)
            or task_name != entry_task_name
            or not editor.is_valid_slug(task_name)
            or len(task_name) > MAX_DRAFT_TASK_NAME_CHARS
            or not isinstance(description, str)
        ):
            return None
        converted = summary.get("converted")
        blocking = summary.get("blocking")
        total = summary.get("total")
        if (
            not isinstance(converted, int)
            or isinstance(converted, bool)
            or converted < 0
            or not isinstance(blocking, int)
            or isinstance(blocking, bool)
            or blocking < 0
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
        ):
            return None
        normalized_operations = []
        stored_operation_digests = []
        for operation in operations:
            if not isinstance(operation, dict):
                return None
            stored_operation_digests.append(
                external_task_migration.operation_fingerprint(operation)
            )
            try:
                normalized_operation = task_authoring.normalize_operation(
                    operation
                )
            except (TypeError, ValueError):
                return None
            if task_authoring.validate_operation(normalized_operation):
                return None
            normalized_operations.append(normalized_operation)
        normalized_provenance = []
        previous_line_number = 0
        operation_offset = 0
        for item in provenance_value:
            if not isinstance(item, dict):
                return None
            line_number = item.get("line_number")
            status_value = item.get("status")
            digest = item.get("instruction_sha256")
            source_entry = item.get("source_entry")
            source_line = item.get("source_line")
            operation_count = item.get("operation_count")
            operation_digests = item.get("operation_digests")
            if (
                not isinstance(line_number, int)
                or isinstance(line_number, bool)
                or line_number < 1
                or status_value not in {
                    "converted", "choice_required", "unresolved"
                }
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not isinstance(source_entry, str)
                or source_entry != entry_name
                or len(source_entry.encode("utf-8"))
                > MAX_DRAFT_SOURCE_ENTRY_BYTES
                or not isinstance(source_line, str)
                or len(source_line.encode("utf-8")) > MAX_DRAFT_SOURCE_LINE_BYTES
                or not isinstance(operation_digests, list)
                or len(operation_digests) != operation_count
                or not all(
                    isinstance(digest_value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", digest_value)
                    for digest_value in operation_digests
                )
                or hashlib.sha256(source_line.encode("utf-8")).hexdigest()
                != digest
                or line_number <= previous_line_number
                or not isinstance(operation_count, int)
                or isinstance(operation_count, bool)
                or operation_count < 1
            ):
                return None
            operation_slice = normalized_operations[
                operation_offset:operation_offset + operation_count
            ]
            if len(operation_slice) != operation_count:
                return None
            expected_digests = stored_operation_digests[
                operation_offset:operation_offset + operation_count
            ]
            if expected_digests != operation_digests:
                return None
            blockers_in_slice = task_authoring.migration_blockers(
                operation_slice
            )
            if status_value == "converted":
                if blockers_in_slice:
                    return None
            elif (
                operation_count != 1
                or len(blockers_in_slice) != 1
                or blockers_in_slice[0]["params"].get("instruction_sha256")
                != digest
            ):
                return None
            normalized_provenance.append({
                "source_entry": source_entry,
                "line_number": line_number,
                "source_line": source_line,
                "instruction_sha256": digest,
                "status": status_value,
                "operation_count": operation_count,
                "operation_digests": operation_digests,
            })
            previous_line_number = line_number
            operation_offset += operation_count
        if operation_offset != len(normalized_operations):
            return None
        actual_converted = sum(
            item["status"] == "converted" for item in normalized_provenance
        )
        actual_blocking = len(task_authoring.migration_blockers(
            normalized_operations
        ))
        actual_total = len(normalized_provenance)
        expected_status = "needs_review" if actual_blocking else "draft_ready"
        if (
            converted != actual_converted
            or blocking != actual_blocking
            or total != actual_total
            or total != converted + blocking
            or entry_status != expected_status
        ):
            return None
        return {
            "task_name": task_name,
            "description": description[:2048],
            "operations": normalized_operations,
            "summary": {
                "converted": converted,
                "blocking": blocking,
                "total": total,
            },
            "disclosures": list(disclosures_value),
            "provenance": normalized_provenance,
        }

    normalized_entries = []
    raw_entries = value.get("entries")
    if isinstance(raw_entries, list):
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            entry_status = raw_entry.get("status")
            if entry_status not in {
                "imported",
                "unresolved",
                "draft_ready",
                "needs_review",
                "failed",
            }:
                continue
            omitted = raw_entry.get("omitted_unresolved", 0)
            if not isinstance(omitted, int) or isinstance(omitted, bool):
                omitted = 0
            entry_name_value = raw_entry.get("entry_name")
            entry_task_name = (
                raw_entry.get("task_name")
                if isinstance(raw_entry.get("task_name"), str)
                else None
            )
            entry_name = (
                entry_name_value
                if isinstance(entry_name_value, str)
                else ""
            )
            normalized_draft = safe_draft(
                raw_entry.get("draft"),
                entry_name=entry_name,
                entry_status=entry_status,
                entry_task_name=entry_task_name,
            )
            if (
                entry_status in {"draft_ready", "needs_review"}
                and normalized_draft is None
            ):
                entry_status = "failed"
                entry_message = (
                    "Stored migration draft is invalid. Re-import the source file."
                )
            else:
                entry_message = str(raw_entry.get("message") or "")[:1024]
            normalized_entries.append({
                "entry_name": entry_name[:MAX_DRAFT_SOURCE_ENTRY_BYTES],
                "status": entry_status,
                "task_name": entry_task_name,
                "message": entry_message,
                "unresolved_lines": safe_text_list(
                    raw_entry.get("unresolved_lines")
                )[:20],
                "omitted_unresolved": max(0, omitted),
                "migration_items": safe_migration_items(
                    raw_entry.get("migration_items")
                ),
                "draft": normalized_draft,
            })

    category = value.get("rejection_category")
    if category not in {
        "quota",
        "unresolved-instructions",
        "archive-validation",
        "unexpected",
        None,
    }:
        category = None
    return {
        "status": status,
        "uploaded_filename": str(value.get("uploaded_filename", ""))[:256],
        "imported_task_names": safe_text_list(
            value.get("imported_task_names")
        ),
        "entries": normalized_entries,
        "rejection_category": category,
    }


def _set_marcedit_import_result(value: object) -> None:
    if not isinstance(value, dict):
        st.session_state.pop(K_MARCEDIT_IMPORT_RESULT, None)
        return
    st.session_state[K_MARCEDIT_IMPORT_RESULT] = value


def _clear_marcedit_import_result() -> None:
    st.session_state.pop(K_MARCEDIT_IMPORT_RESULT, None)
    st.session_state.pop(K_MARCEDIT_IMPORT_ADOPTED_ENTRY, None)


def _adopt_migration_draft(
    draft: dict,
    *,
    entry_name: str | None = None,
    entry_key: str | None = None,
) -> None:
    """Move one validated import draft into editor state without persistence."""

    _open_editor_for_new()
    name = str(draft.get("task_name") or "")
    description = str(draft.get("description") or "")
    st.session_state[K_EDITOR_NAME] = name
    st.session_state[K_EDITOR_DESCRIPTION] = description
    _sync_editor_widget_inputs(name, description)
    st.session_state[K_EDITOR_OPS] = copy.deepcopy(draft.get("operations") or [])
    st.session_state[K_EDITOR_BODY] = ""
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_IMPORT_SUMMARY] = copy.deepcopy(
        draft.get("summary") or {}
    )
    st.session_state[K_EDITOR_IMPORT_PROVENANCE] = copy.deepcopy(
        draft.get("provenance") or []
    )
    st.session_state[K_EDITOR_IMPORT_DISCLOSURES] = copy.deepcopy(
        draft.get("disclosures") or []
    )
    st.session_state[K_EDITOR_IMPORT_SOURCE] = {
        "entry_name": entry_name or "",
        "task_name": name,
        "description": description,
    }
    st.session_state[K_MARCEDIT_IMPORT_ADOPTED_ENTRY] = entry_key
    _reset_operation_dialog_state()


def _draft_result_entry(
    draft: external_task_migration.MigrationDraft,
    *,
    entry_name: str,
) -> dict:
    return {
        "entry_name": entry_name,
        "status": draft.status,
        "task_name": draft.task_name,
        "message": (
            "editable draft is ready"
            if draft.status == "draft_ready"
            else "editable draft contains instructions needing review"
        ),
        "draft": draft.to_session_dict(),
    }


def _render_marcedit_import_result() -> None:
    raw = _normalize_marcedit_import_result(
        st.session_state.get(K_MARCEDIT_IMPORT_RESULT)
    )
    if not raw:
        if K_MARCEDIT_IMPORT_RESULT in st.session_state:
            logger.warning(
                "Dropped malformed tasks import diagnostics from session state."
            )
            st.session_state.pop(K_MARCEDIT_IMPORT_RESULT, None)
            st.error(
                "Stored import result is invalid. Re-import the source file."
            )
        return

    filename = raw["uploaded_filename"]
    imported_task_names = list(raw.get("imported_task_names") or [])
    entries = list(raw.get("entries") or [])
    status = raw["status"]
    category = raw.get("rejection_category")

    st.markdown("### Imported task drafts")
    if status == "success":
        if entries:
            ready_count = sum(
                entry.get("status") == "draft_ready" for entry in entries
            )
            st.success(
                f"{ready_count} editable task draft(s) are ready from `{filename}`."
            )
        elif imported_task_names:
            st.success(
                f"Imported {len(imported_task_names)} task(s) from `{filename}`."
            )
            for task_name in imported_task_names:
                st.success(f"- `{task_name}`")
        else:
            st.success(f"Import from `{filename}` completed with no saved tasks.")
    elif status == "partial":
        if category == "unresolved-instructions":
            st.warning(
                "Some instructions need your confirmation. Open the editable "
                "draft to review the suggested structured operations."
            )
        else:
            st.warning(
                f"Import completed with warnings from `{filename}`. "
                f"{len(imported_task_names)} task(s) imported."
            )
        for task_name in imported_task_names:
            st.success(f"- `{task_name}`")
    else:
        if category == "quota":
            st.error(f"Import rejected (`{filename}`): quota exceeded.")
        elif category == "unresolved-instructions":
            st.warning(
                "Some instructions need your confirmation. Open the editable "
                "draft to review the suggested structured operations."
            )
        elif category == "archive-validation":
            st.error(f"Import from `{filename}` was rejected due to archive validation.")
        else:
            st.error(f"Import from `{filename}` failed.")

    adopted_entry = st.session_state.get(K_MARCEDIT_IMPORT_ADOPTED_ENTRY)
    draft_entries = [
        (index, entry)
        for index, entry in enumerate(entries)
        if isinstance(entry.get("draft"), dict)
        and str(index) != adopted_entry
    ]
    if len(draft_entries) > 1:
        labels = [
            "{0}. {1} — {2}".format(
                index + 1,
                entry.get("task_name") or "Untitled task",
                entry.get("entry_name") or filename,
            )
            for index, entry in draft_entries
        ]
        selected = st.selectbox(
            "Choose an imported task draft",
            labels,
            key="tasks_import_draft_choice",
        )
        selected_offset = labels.index(selected)
        selected_entry = draft_entries[selected_offset][1]
        if st.button("Open selected draft", key="tasks_import_open_selected"):
            _adopt_migration_draft(
                selected_entry["draft"],
                entry_name=selected_entry.get("entry_name") or filename,
                entry_key=str(draft_entries[selected_offset][0]),
            )
            st.rerun()
            return

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_name = entry.get("entry_name") or filename
        entry_status = entry.get("status") or ""
        task_name = entry.get("task_name")
        entry_message = entry.get("message") or ""
        if str(index) == adopted_entry:
            st.success(f"{entry_name}: opened in the task editor.")
            continue

        if entry_status == "imported":
            if task_name:
                st.success(f"{entry_name} → `{task_name}`")
            else:
                st.success(f"Imported from `{entry_name}`.")
            continue

        if entry_status in {"draft_ready", "needs_review"}:
            if entry_status == "draft_ready":
                st.success(f"{entry_name}: editable draft ready.")
            else:
                st.warning(
                    f"{entry_name}: editable draft needs migration review."
                )
            if len(draft_entries) == 1 and isinstance(entry.get("draft"), dict):
                if st.button(
                    "Open migration draft",
                    key=f"tasks_import_open_draft_{index}",
                ):
                    _adopt_migration_draft(
                        entry["draft"],
                        entry_name=entry_name,
                        entry_key=str(index),
                    )
                    st.rerun()
                    return
            continue

        if entry_status == "unresolved":
            if entry_message:
                st.warning(f"{entry_name}: {entry_message}")
            else:
                st.warning(f"{entry_name}: unresolved external instructions.")
            if task_name:
                st.caption(f"Task: `{task_name}`")
            for line in list(entry.get("unresolved_lines") or [])[:20]:
                st.code(line, language="text")
            migration_items = entry.get("migration_items") or []
            if migration_items:
                st.markdown("**Migration review**")
                if st.button(
                    "Open ordered migration review",
                    key=f"migration_review_{entry_name}",
                ):
                    _open_migration_review(migration_items, filename)
                for item in migration_items:
                    status = item.get("status", "unresolved")
                    source_line = item.get("source_line", "")
                    reason = item.get("reason", "")
                    digest = item.get("instruction_sha256", "")
                    if status == "choice_required":
                        st.warning(
                            f"Choice required: {reason}. The original instruction is preserved."
                        )
                        choices = item.get("choices") or []
                        if choices:
                            st.caption(
                                "Choose an explicit operation to open in the task editor:"
                            )
                            for choice in choices:
                                if st.button(
                                    f"Use {choice}",
                                    key=f"migration_choice_{digest[:16]}_{choice}",
                                ):
                                    _open_empty_find_migration(
                                        source_line,
                                        choice,
                                        filename,
                                    )
                    else:
                        st.caption(f"{status}: {reason}")
                    cataloger_action = str(
                        item.get("cataloger_action") or ""
                    ).strip()
                    if cataloger_action:
                        st.info("Next: " + cataloger_action)
                    if source_line:
                        st.code(source_line, language="text")
                    if digest:
                        st.caption(f"Instruction fingerprint: `{digest}`")
            omitted = entry.get("omitted_unresolved", 0)
            if omitted:
                st.caption(f"{omitted} additional unresolved lines omitted.")
            continue

        if entry_message:
            st.error(f"{entry_name}: {entry_message}")
        else:
            st.error(f"{entry_name}: operation could not be imported.")

    if st.button("Dismiss", key="tasks_import_diagnostics_dismiss"):
        _clear_marcedit_import_result()
        st.rerun()


def _open_empty_find_migration(
    source_line: str,
    choice: str,
    filename: str,
) -> None:
    """Open one explicitly resolved empty-find line in the normal editor."""
    item = external_task_migration.adapt_subfield_edit(
        source_line,
        empty_find_choice=choice,
    )
    if item.status != "converted" or item.operation is None:
        st.error(item.reason or "That migration choice could not be converted.")
        return
    _open_editor_for_new()
    base = marcedit_import._derive_name_from_filename(filename)
    st.session_state[K_EDITOR_NAME] = f"{base}-migration"
    st.session_state[K_EDITOR_DESCRIPTION] = (
        f"Explicit migration of one empty-find instruction from {filename}"
    )
    _sync_editor_widget_inputs(
        st.session_state[K_EDITOR_NAME],
        st.session_state[K_EDITOR_DESCRIPTION],
    )
    st.session_state[K_EDITOR_OPS] = [item.operation]
    st.session_state[K_EDITOR_BODY] = ""
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    _clear_marcedit_import_result()
    _reset_operation_dialog_state()
    st.rerun()


def _open_migration_review(items: list[dict], filename: str) -> None:
    """Open all converted and blocking cards in source order.

    Blocking cards are preserved as technical custom operations with an
    authoring error, so the normal save gate prevents accidental execution
    until the cataloger replaces or removes each one.
    """
    operations: list[dict] = []
    for item in items:
        if item.get("status") == "converted" and isinstance(
            item.get("operation"), dict
        ):
            operations.append(copy.deepcopy(item["operation"]))
            continue
        source_line = str(item.get("source_line") or "")
        reason = str(item.get("reason") or "unresolved external instruction")
        operations.append({
            "kind": "custom",
            "params": {
                "code": f"# TODO: {reason}\n# SOURCE: {source_line}",
            },
            "authoring_error": reason,
        })
    _open_editor_for_new()
    base = marcedit_import._derive_name_from_filename(filename)
    st.session_state[K_EDITOR_NAME] = f"{base}-migration"
    st.session_state[K_EDITOR_DESCRIPTION] = (
        f"Migration review from {filename}; replace every blocking card"
    )
    _sync_editor_widget_inputs(
        st.session_state[K_EDITOR_NAME],
        st.session_state[K_EDITOR_DESCRIPTION],
    )
    st.session_state[K_EDITOR_OPS] = operations
    st.session_state[K_EDITOR_BODY] = ""
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    _clear_marcedit_import_result()
    _reset_operation_dialog_state()
    st.rerun()


def _render_run_mode(registered, tasks_dir: Path) -> None:
    """Run saved tasks against the loaded batch and review the results."""
    st.subheader("Run on loaded batch")
    if not session.has_upload():
        # Don't use session.require_upload() here — the standard banner
        # says "this feature reads records already in this session,"
        # but Tasks can be *authored* without a loaded batch (we want
        # the user to keep building/importing tasks even pre-upload).
        # A bespoke message is the right call.
        st.info(
            "Upload a `.mrc` file on the **Home** page to run tasks "
            "against it. Tasks can be built and imported without a "
            "loaded batch."
        )
    elif not registered:
        st.info(
            "Create or import at least one task in **Build & import** "
            "to enable running."
        )
    else:
        _render_run_panel(registered, tasks_dir)
        _render_sync_run_result()


def _render_saved_tasks(registered, tasks_dir: Path) -> None:
    """Render the saved-task Run workflow."""
    _render_run_mode(registered, tasks_dir)


def _render_create_workspace(
    tasks_dir: Path,
    is_admin: bool,
    current_user_id: str,
    registered,
) -> None:
    """Render task authoring without importing or library navigation."""
    st.subheader("Create task")
    counts = task_db.count_visible(current_user_id)
    own_tasks = task_db.list_own_tasks(current_user_id)
    cnt_a, cnt_b, cnt_c, cnt_d = st.columns([2, 2, 2, 2])
    cnt_a.metric("Yours", counts["own"])
    cnt_b.metric("Shared with you", counts["shared_from_others"])
    cnt_c.metric("Registered", len(registered))
    if cnt_d.button("Clear my tasks", key="tasks_clear_mine"):
        for task in own_tasks:
            task_db.delete_task(current_user_id, task["name"])
            tasks.TASK_REGISTRY.pop(task["name"], None)
        st.session_state[K_EDITOR_OPEN] = False
        _reset_operation_dialog_state()
        st.rerun()
    if not is_admin:
        st.caption(
            "ℹ️ You're using the **form builder** path. Raw-Python task "
            "authoring is restricted to administrators."
        )
    if st.button("+ New task", key="tasks_new"):
        _open_editor_for_new()
        st.rerun()
    _render_ai_draft_panel()
    if st.session_state.get(K_AI_DRAFT_REVIEW) is not None:
        _render_ai_draft_review()
    if st.session_state[K_EDITOR_OPEN]:
        _render_editor(tasks_dir, is_admin)


def _render_import_workspace(
    tasks_dir: Path,
    current_user_id: str,
    registered,
) -> None:
    """Render task-file import and its non-widget result/draft state."""
    del current_user_id, registered
    st.subheader("Import task")
    upl = st.file_uploader(
        "Import a MarcEdit .tasksfile (`.txt`) or `.task` archive",
        type=["txt", "task"],
        accept_multiple_files=False,
        key="tasks_import_uploader",
    )
    if upl is not None and st.button("Import", key="tasks_import_btn"):
        _do_marcedit_import(upl, tasks_dir)
        st.rerun()
    if st.session_state.get(K_MARCEDIT_IMPORT_RESULT) is not None:
        _render_marcedit_import_result()


def _render_quick_ops_mode() -> None:
    """One-shot find/replace and canned batch operations."""
    if not session.has_upload():
        st.info(
            "Upload a `.mrc` file on the **Home** page to use quick "
            "operations."
        )
        return
    _render_quick_find_replace()
    _render_quick_batch_operations()


def _folder_children(
    folders: list[dict[str, Any]],
    *,
    scope: str,
    parent_id: int | None,
) -> list[dict[str, Any]]:
    return sorted(
        [
            folder
            for folder in folders
            if folder["scope"] == scope
            and folder.get("parent_id") == parent_id
        ],
        key=lambda folder: str(folder["name"]).casefold(),
    )


def _folder_descendants(
    folders: list[dict[str, Any]], folder_id: int,
) -> set[int]:
    children: dict[int | None, list[int]] = {}
    for folder in folders:
        parent = folder.get("parent_id")
        children.setdefault(parent, []).append(int(folder["id"]))
    found: set[int] = set()
    pending = list(children.get(folder_id, []))
    while pending:
        child = pending.pop()
        if child in found:
            continue
        found.add(child)
        pending.extend(children.get(child, []))
    return found


def _folder_path_map(
    folders: list[dict[str, Any]],
) -> dict[int, str]:
    by_id = {int(folder["id"]): folder for folder in folders}
    paths: dict[int, str] = {}
    for folder_id, folder in by_id.items():
        names: list[str] = []
        current = folder_id
        seen: set[int] = set()
        while current in by_id and current not in seen:
            seen.add(current)
            current_folder = by_id[current]
            names.append(str(current_folder["name"]))
            parent = current_folder.get("parent_id")
            current = int(parent) if parent is not None else -1
        scope_label = "Shared Tasks" if folder["scope"] == "shared" else "My Tasks"
        paths[folder_id] = " / ".join([scope_label, *reversed(names)])
    return paths


def _render_folder_node(
    folders: list[dict[str, Any]],
    *,
    scope: str,
    parent_id: int | None,
    depth: int = 0,
) -> None:
    for folder in _folder_children(
        folders, scope=scope, parent_id=parent_id
    ):
        folder_id = int(folder["id"])
        count = len(folder.get("task_ids") or [])
        prefix = "　" * depth
        if st.button(
            f"{prefix}📁 {folder['name']} ({count})",
            key=f"tasks_library_folder_{folder_id}",
            use_container_width=True,
            type=(
                "primary"
                if st.session_state.get(K_LIBRARY_FOLDER_ID) == folder_id
                else "secondary"
            ),
        ):
            st.session_state[K_LIBRARY_FOLDER_ID] = folder_id
            st.session_state[K_LIBRARY_SCOPE] = scope
            st.rerun()
        _render_folder_node(
            folders,
            scope=scope,
            parent_id=folder_id,
            depth=depth + 1,
        )


def _render_library_dialog() -> None:
    """Render the one non-nested folder/task organization dialog."""
    mode = st.session_state.get(K_LIBRARY_DIALOG)
    actor = session.current_user_id()
    folders = task_library.list_folder_tree(actor)
    paths = _folder_path_map(folders)
    error_key = "tasks_library_dialog_error"
    if mode == "folder-create":
        scope = st.session_state.get(K_LIBRARY_SCOPE, "personal")
        st.markdown(
            "Create a folder under the selected compatible parent. "
            "Folder depth is limited to three levels."
        )
        name = st.text_input("Folder name", key="tasks_library_dialog_name")
        options = [
            folder for folder in folders if folder["scope"] == scope
        ]
        option_ids = [None] + [int(folder["id"]) for folder in options]
        selected = st.selectbox(
            "Parent folder",
            option_ids,
            format_func=lambda value: (
                f"{paths[int(value)]}"
                if value is not None else "Root"
            ),
            key="tasks_library_dialog_parent",
            index=(
                option_ids.index(st.session_state.get(K_LIBRARY_DIALOG_FOLDER))
                if st.session_state.get(K_LIBRARY_DIALOG_FOLDER) in option_ids
                else 0
            ),
        )
        if st.button("Create folder", type="primary", key="tasks_library_dialog_save"):
            try:
                task_library.create_folder(
                    actor,
                    scope=scope,
                    parent_id=selected,
                    name=name,
                )
            except ValueError as exc:
                st.session_state[error_key] = str(exc)
            else:
                st.session_state[K_LIBRARY_DIALOG] = None
                st.session_state.pop(error_key, None)
                st.rerun()
    elif mode in {"folder-rename", "folder-move", "folder-delete"}:
        folder_id = st.session_state.get(K_LIBRARY_DIALOG_FOLDER)
        folder = next(
            (item for item in folders if int(item["id"]) == folder_id),
            None,
        )
        if folder is None:
            st.error("That folder is no longer available. Refresh the library.")
            return
        st.markdown(f"**{paths[folder_id]}**")
        if mode == "folder-rename":
            name = st.text_input(
                "New folder name",
                value=str(folder["name"]),
                key="tasks_library_dialog_name",
            )
            if st.button("Rename folder", type="primary", key="tasks_library_dialog_save"):
                try:
                    task_library.rename_folder(
                        actor,
                        folder_id=folder_id,
                        new_name=name,
                        expected_revision=folder["revision"],
                    )
                except ValueError as exc:
                    st.session_state[error_key] = str(exc)
                else:
                    st.session_state[K_LIBRARY_DIALOG] = None
                    st.session_state.pop(error_key, None)
                    st.rerun()
        elif mode == "folder-move":
            excluded = {folder_id} | _folder_descendants(folders, folder_id)
            options = [
                item for item in folders
                if item["scope"] == folder["scope"]
                and int(item["id"]) not in excluded
            ]
            root_options = [
                int(item["id"]) for item in options if item["parent_id"] is None
            ]
            parent_ids = [None] + [
                int(item["id"])
                for item in options
                if item["parent_id"] is not None
            ]
            selected = st.selectbox(
                "New parent folder",
                parent_ids,
                format_func=lambda value: (
                    "Root"
                    if value is None
                    else paths[int(value)]
                ),
                key="tasks_library_dialog_parent",
            )
            # The service accepts only a real folder ID. A root folder is the
            # actual destination for a conceptual root move.
            if selected is None:
                selected = root_options[0] if root_options else None
            if st.button("Move folder", type="primary", key="tasks_library_dialog_save"):
                try:
                    if selected is None:
                        raise ValueError("a compatible parent folder is required")
                    task_library.move_folder(
                        actor,
                        folder_id=folder_id,
                        parent_id=selected,
                        expected_revision=folder["revision"],
                    )
                except ValueError as exc:
                    st.session_state[error_key] = str(exc)
                else:
                    st.session_state[K_LIBRARY_DIALOG] = None
                    st.session_state.pop(error_key, None)
                    st.rerun()
        else:
            st.warning("Folders must be empty before they can be deleted.")
            if st.button("Delete folder", type="primary", key="tasks_library_dialog_save"):
                try:
                    task_library.delete_folder(
                        actor,
                        folder_id=folder_id,
                        expected_revision=folder["revision"],
                    )
                except ValueError as exc:
                    st.session_state[error_key] = str(exc)
                else:
                    st.session_state[K_LIBRARY_DIALOG] = None
                    st.session_state[K_LIBRARY_FOLDER_ID] = None
                    st.session_state.pop(error_key, None)
                    st.rerun()
    elif mode in {"task-move", "task-share", "task-unshare"}:
        task_id = st.session_state.get(K_LIBRARY_DIALOG_TASK)
        task = task_library.get_task_for_actor(actor, int(task_id))
        if task is None:
            st.error("That task is no longer available. Refresh the library.")
            return
        if mode == "task-share":
            options = [item for item in folders if item["scope"] == "shared"]
            label = "Shared destination"
        elif mode == "task-unshare":
            options = [
                item for item in folders
                if item["scope"] == "personal"
                and item["owner_email"] == actor
            ]
            label = "Personal destination"
        else:
            options = [
                item for item in folders
                if (
                    item["scope"] == (
                        "shared" if task["visibility"] == "shared" else "personal"
                    )
                    and (
                        task["visibility"] == "shared"
                        or item["owner_email"] == actor
                    )
                )
            ]
            label = "Destination folder"
        if not options:
            st.error("No compatible destination folders are available.")
            return
        option_ids = [int(item["id"]) for item in options]
        selected = st.selectbox(
            label,
            option_ids,
            format_func=lambda value: paths[int(value)],
            key="tasks_library_dialog_destination",
        )
        action_label = {
            "task-share": "Share task",
            "task-unshare": "Move to personal tasks",
            "task-move": "Move task",
        }[mode]
        if st.button(action_label, type="primary", key="tasks_library_dialog_save"):
            try:
                if mode == "task-share":
                    task_library.share_task(
                        actor,
                        task_id=task_id,
                        folder_id=selected,
                        expected_revision=task["revision"],
                    )
                elif mode == "task-unshare":
                    task_library.unshare_task(
                        actor,
                        task_id=task_id,
                        folder_id=selected,
                        expected_revision=task["revision"],
                    )
                else:
                    task_library.move_task(
                        actor,
                        task_id=task_id,
                        folder_id=selected,
                        expected_revision=task["revision"],
                    )
            except ValueError as exc:
                st.session_state[error_key] = str(exc)
            else:
                st.session_state[K_LIBRARY_DIALOG] = None
                st.session_state.pop(error_key, None)
                st.rerun()
    if st.session_state.get(error_key):
        st.error(st.session_state[error_key])


def _show_library_dialog() -> None:
    wrapper = st.dialog(
        "Task library organization",
        width="small",
        dismissible=False,
    )(_render_library_dialog)
    wrapper()


def _open_library_dialog(mode: str, *, folder_id: int | None = None, task_id: int | None = None) -> None:
    st.session_state[K_LIBRARY_DIALOG] = mode
    st.session_state[K_LIBRARY_DIALOG_FOLDER] = folder_id
    st.session_state[K_LIBRARY_DIALOG_TASK] = task_id
    _show_library_dialog()


def _render_task_library(
    *,
    current_user_id: str,
    is_admin: bool,
) -> None:
    """Render the persistent folder explorer and authorized task results."""
    folders = task_library.list_folder_tree(current_user_id)
    by_id = {int(folder["id"]): folder for folder in folders}
    selected_folder_id = st.session_state.get(K_LIBRARY_FOLDER_ID)
    if selected_folder_id is not None and selected_folder_id not in by_id:
        st.session_state[K_LIBRARY_FOLDER_ID] = None
        selected_folder_id = None

    left, right = st.columns([1, 3])
    with left:
        st.markdown("**Task folders**")
        if st.button("+ Personal folder", key="tasks_library_new_personal"):
            st.session_state[K_LIBRARY_SCOPE] = "personal"
            _open_library_dialog("folder-create")
        if st.button("+ Shared folder", key="tasks_library_new_shared"):
            st.session_state[K_LIBRARY_SCOPE] = "shared"
            _open_library_dialog("folder-create")
        for scope, label in (("personal", "My Tasks"), ("shared", "Shared Tasks")):
            if st.button(
                label,
                key=f"tasks_library_scope_{scope}",
                use_container_width=True,
                type=(
                    "primary"
                    if st.session_state.get(K_LIBRARY_SCOPE) == scope
                    and selected_folder_id is None
                    else "secondary"
                ),
            ):
                st.session_state[K_LIBRARY_SCOPE] = scope
                st.session_state[K_LIBRARY_FOLDER_ID] = None
                st.rerun()
            _render_folder_node(
                folders,
                scope=scope,
                parent_id=None,
            )

    with right:
        selected_folder = by_id.get(selected_folder_id)
        if selected_folder is not None:
            st.caption(
                _folder_path_map(folders).get(
                    selected_folder_id, selected_folder["name"]
                )
            )
            action_cols = st.columns(4)
            if action_cols[0].button(
                "New subfolder", key="tasks_library_new_child"
            ):
                st.session_state[K_LIBRARY_SCOPE] = selected_folder["scope"]
                _open_library_dialog(
                    "folder-create", folder_id=selected_folder_id
                )
            if action_cols[1].button(
                "Rename",
                key="tasks_library_rename_folder",
                disabled=selected_folder["parent_id"] is None,
                help=(
                    "The Unfiled root is a stable library anchor."
                    if selected_folder["parent_id"] is None
                    else None
                ),
            ):
                _open_library_dialog("folder-rename", folder_id=selected_folder_id)
            if action_cols[2].button(
                "Move",
                key="tasks_library_move_folder",
                disabled=selected_folder["parent_id"] is None,
                help=(
                    "The Unfiled root is a stable library anchor."
                    if selected_folder["parent_id"] is None
                    else None
                ),
            ) and selected_folder["parent_id"] is not None:
                _open_library_dialog("folder-move", folder_id=selected_folder_id)
            if action_cols[3].button(
                "Delete",
                key="tasks_library_delete_folder",
                disabled=selected_folder["parent_id"] is None,
                help=(
                    "The Unfiled root is a stable library anchor."
                    if selected_folder["parent_id"] is None
                    else None
                ),
            ):
                _open_library_dialog("folder-delete", folder_id=selected_folder_id)

        st.markdown("**Search tasks**")
        st.text_input(
            "Search name, description, operation, tag, literal, or source",
            key=K_LIBRARY_QUERY,
        )
        filter_cols = st.columns(3)
        filter_cols[0].selectbox(
            "Visibility",
            ["all", "private", "shared"],
            format_func=lambda value: {
                "all": "All visible",
                "private": "My tasks",
                "shared": "Shared tasks",
            }[value],
            key=K_LIBRARY_VISIBILITY,
        )
        filter_cols[1].selectbox(
            "Validation",
            ["all", "valid", "legacy", "invalid"],
            key=K_LIBRARY_VALIDATION,
        )
        filter_cols[2].selectbox(
            "Updated",
            ["any", "7", "30"],
            format_func=lambda value: {
                "any": "Any time",
                "7": "Last 7 days",
                "30": "Last 30 days",
            }[value],
            key=K_LIBRARY_RECENT,
        )
        detail_cols = st.columns(4)
        detail_cols[0].text_input("Owner", key=K_LIBRARY_OWNER)
        detail_cols[1].text_input("MARC tag", key=K_LIBRARY_TAG)
        detail_cols[2].text_input("Subfield", max_chars=1, key=K_LIBRARY_SUBFIELD)
        kind_options = ["all"] + [
            entry["kind"]
            for entry in sorted(
                OPERATIONS_PALETTE,
                key=lambda entry: str(entry["label"]).casefold(),
            )
        ]
        detail_cols[3].selectbox(
            "Operation",
            kind_options,
            format_func=lambda value: (
                "All operations"
                if value == "all"
                else next(
                    entry["label"]
                    for entry in OPERATIONS_PALETTE
                    if entry["kind"] == value
                )
            ),
            key=K_LIBRARY_KIND,
        )
        visibility = st.session_state[K_LIBRARY_VISIBILITY]
        folder_scope = st.session_state.get(K_LIBRARY_SCOPE, "all")
        if visibility == "all":
            visibility = None
        if visibility is None and selected_folder_id is None:
            visibility = {
                "personal": "private",
                "shared": "shared",
            }.get(folder_scope)
        try:
            results = task_library_search.search_visible_tasks(
                current_user_id,
                st.session_state.get(K_LIBRARY_QUERY, ""),
                operation_kind=(
                    None if st.session_state[K_LIBRARY_KIND] == "all"
                    else st.session_state[K_LIBRARY_KIND]
                ),
                marc_tag=st.session_state.get(K_LIBRARY_TAG, "").strip() or None,
                visibility=visibility,
                folder_id=selected_folder_id,
                owner=st.session_state.get(K_LIBRARY_OWNER, "").strip() or None,
                subfield_code=st.session_state.get(K_LIBRARY_SUBFIELD, "").strip() or None,
                validation_state=(
                    None if st.session_state[K_LIBRARY_VALIDATION] == "all"
                    else st.session_state[K_LIBRARY_VALIDATION]
                ),
                recent_days=(
                    None if st.session_state[K_LIBRARY_RECENT] == "any"
                    else int(st.session_state[K_LIBRARY_RECENT])
                ),
            )
        except ValueError as exc:
            st.error(str(exc))
            results = []
        st.caption(f"{len(results)} task(s)")
        if not results:
            st.info("No visible tasks match these filters.")
        for result in results:
            row = task_db.get_task(result["owner_email"], result["name"])
            if row is None:
                continue
            owned = result["owner_email"] == current_user_id
            editable = owned or result["visibility"] == "shared"
            result_cols = st.columns([3, 3, 2, 1, 1, 1, 1])
            result_cols[0].markdown(
                f"**`{result['name']}`**" +
                ("  :material/share: shared" if result["visibility"] == "shared" else "")
            )
            result_cols[1].caption(result["description"] or "(no description)")
            result_cols[2].caption(
                f"{result['folder_path'] or 'Unfiled'} · {result['operation_count']} operation(s)"
            )
            if editable:
                if result_cols[3].button(
                    "Edit",
                    key=f"tasks_library_edit_{result['id']}",
                    help=(
                        "Edit shared content without changing its owner; "
                        "the edit is audited."
                        if not owned
                        else None
                    ),
                ):
                    _open_editor_for_existing_row(row, is_admin)
                    st.rerun()
                if owned and result_cols[4].button(
                    "Share" if result["visibility"] == "private" else "Unshare",
                    key=f"tasks_library_share_{result['id']}",
                ):
                    _open_library_dialog(
                        "task-share" if result["visibility"] == "private" else "task-unshare",
                        task_id=int(result["id"]),
                    )
            else:
                result_cols[3].caption("read-only")
            if result_cols[5].button("Move", key=f"tasks_library_move_{result['id']}"):
                _open_library_dialog("task-move", task_id=int(result["id"]))
            if owned and result_cols[6].button(
                "Delete", key=f"tasks_library_delete_{result['id']}"
            ):
                task_db.delete_task(current_user_id, result["name"])
                tasks.TASK_REGISTRY.pop(result["name"], None)
                audit_event(
                    "task-deleted",
                    user=current_user_id,
                    task_name=result["name"],
                )
                st.rerun()


def _render_build_mode(
    tasks_dir: Path, is_admin: bool, current_user_id: str, registered
) -> None:
    """Manage, author, and import task definitions."""
    # --- Counts banner + admin badge --------------------------------------

    counts = task_db.count_visible(current_user_id)
    own_tasks = task_db.list_own_tasks(current_user_id)
    cnt_a, cnt_b, cnt_c, cnt_d = st.columns([2, 2, 2, 2])
    cnt_a.metric("Yours", counts["own"])
    cnt_b.metric("Shared with you", counts["shared_from_others"])
    cnt_c.metric("Registered", len(registered))
    if cnt_d.button("Clear my tasks", key="tasks_clear_mine"):
        for t in own_tasks:
            try:
                task_db.delete_task(current_user_id, t["name"])
                tasks.TASK_REGISTRY.pop(t["name"], None)
            except Exception as exc:  # noqa: BLE001
                logger.exception("delete_task failed for %s", t["name"])
                st.warning(f"Could not delete {t['name']}: {exc}")
        st.session_state[K_EDITOR_OPEN] = False
        _reset_operation_dialog_state()
        st.rerun()

    if not is_admin:
        st.caption(
            "ℹ️ You're using the **form builder** path. Raw-Python task "
            "authoring is restricted to administrators (see "
            "`MARCEDIT_WEB_ADMINS`)."
        )

    # --- Existing tasks explorer ------------------------------------------

    st.subheader("Task library")
    _render_task_library(
        current_user_id=current_user_id,
        is_admin=is_admin,
    )

    # --- New / import controls --------------------------------------------

    col_new, col_import = st.columns(2)
    with col_new:
        if st.button("+ New task", key="tasks_new"):
            _open_editor_for_new()
            st.rerun()
    with col_import:
        upl = st.file_uploader(
            "Import a MarcEdit .tasksfile (`.txt`) or `.task` archive",
            type=["txt", "task"],
            accept_multiple_files=False,
            key="tasks_import_uploader",
        )
        if upl is not None and st.button("Import", key="tasks_import_btn"):
            _do_marcedit_import(upl, tasks_dir)
            st.rerun()

    if st.session_state.get(K_MARCEDIT_IMPORT_RESULT) is not None:
        _render_marcedit_import_result()

    _render_ai_draft_panel()
    if st.session_state.get(K_AI_DRAFT_REVIEW) is not None:
        _render_ai_draft_review()

    # --- Editor (form or code) --------------------------------------------

    if st.session_state[K_EDITOR_OPEN]:
        _render_editor(tasks_dir, is_admin)


# ---------------------------------------------------------------------------
# Editor state helpers
# ---------------------------------------------------------------------------


def _reset_operation_dialog_state() -> None:
    st.session_state[K_OPERATION_DIALOG_STATE] = None
    st.session_state[K_OPERATION_DIALOG_NONCE] = 0
    st.session_state[K_OPERATION_REFERENCE_REQUESTED] = False
    st.session_state.pop(K_OPERATION_CARDS_PENDING_REMOVE, None)


def _open_editor_for_new() -> None:
    """Open the editor for a brand-new task in form mode."""
    current = st.session_state.get(K_WORKSPACE_LOCATION, WorkspaceLocation())
    _write_workspace_location(dataclasses.replace(current, view="create"))
    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_MODE] = "form"
    st.session_state[K_EDITOR_NAME] = ""
    st.session_state[K_EDITOR_DESCRIPTION] = ""
    _sync_editor_widget_inputs("", "")
    st.session_state[K_EDITOR_BODY] = (
        "# `record` is a pymarc.Record. Mutate it in place; do not return.\n"
        "# Example: delete every 029 field.\n"
        "#\n"
        "# from marcedit_web.lib.transforms import delete_tags\n"
        "# delete_tags(record, \"029\")\n"
        "pass\n"
    )
    st.session_state[K_EDITOR_OPS] = []
    st.session_state[K_EDITOR_ORIGINAL_NAME] = None
    st.session_state[K_EDITOR_ORIGINAL_OWNER] = None
    st.session_state[K_EDITOR_PRESERVE_BODY] = False
    st.session_state[K_EDITOR_VISIBILITY] = "private"
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None
    for key in (
        K_EDITOR_IMPORT_SUMMARY,
        K_EDITOR_IMPORT_PROVENANCE,
        K_EDITOR_IMPORT_DISCLOSURES,
        K_EDITOR_IMPORT_SOURCE,
    ):
        st.session_state.pop(key, None)
    _reset_operation_dialog_state()


def _open_editor_for_existing_row(row: dict, is_admin: bool) -> None:
    """Open the editor pre-populated from a SQL task row.

    ``row`` is a dict from ``task_db.list_visible_tasks`` /
    ``task_db.get_task`` — has ``name``, ``description``, ``body``,
    ``visibility``. Form vs code mode is chosen by re-parsing the
    body via ``task_builder.parse_ops_from_source`` (same logic as
    the legacy file-based path).
    """
    current = st.session_state.get(K_WORKSPACE_LOCATION, WorkspaceLocation())
    _write_workspace_location(dataclasses.replace(current, view="create"))
    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_NAME] = row["name"]
    st.session_state[K_EDITOR_DESCRIPTION] = row["description"]
    _sync_editor_widget_inputs(row["name"], row["description"])
    st.session_state[K_EDITOR_BODY] = row["body"]
    st.session_state[K_EDITOR_ORIGINAL_NAME] = row["name"]
    st.session_state[K_EDITOR_ORIGINAL_OWNER] = (
        row.get("owner_email") or session.current_user_id()
    )
    st.session_state[K_EDITOR_VISIBILITY] = row["visibility"]
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None
    for key in (
        K_EDITOR_IMPORT_SUMMARY,
        K_EDITOR_IMPORT_PROVENANCE,
        K_EDITOR_IMPORT_DISCLOSURES,
        K_EDITOR_IMPORT_SOURCE,
    ):
        st.session_state.pop(key, None)
    _reset_operation_dialog_state()

    parse_result = task_builder.parse_ops_from_source(row["body"])
    if parse_result["form_editable"]:
        st.session_state[K_EDITOR_MODE] = "form"
        st.session_state[K_EDITOR_PRESERVE_BODY] = False
        parsed_ops = [
            op.to_dict() for op in parse_result["ops"]
        ]
        st.session_state[K_EDITOR_OPS] = (
            task_authoring.normalize_operations_for_editor(parsed_ops)
        )
    else:
        # Hand-written: code mode if admin, else read-only-style notice.
        st.session_state[K_EDITOR_MODE] = "code" if is_admin else "form"
        st.session_state[K_EDITOR_PRESERVE_BODY] = not is_admin
        st.session_state[K_EDITOR_OPS] = []


def _archive_scratch_path(tasks_dir: Path, upl_name: str) -> Path:
    """Return a traversal-safe scratch path inside ``tasks_dir`` for an upload.

    The client-supplied filename is reduced to a bare basename (NUL stripped)
    and prefixed with a unique token, so it can never redirect the write
    outside ``tasks_dir`` (path traversal) and concurrent imports of like-named
    files don't collide. The ``.__import__<uuid>_`` prefix is load-bearing for
    safety, not just collisions: it keeps even a basename of ``..`` a literal
    child filename rather than resolving to the parent directory. (TASK-071)
    """
    safe = Path(upl_name).name.replace("\x00", "") or "import.task"
    return tasks_dir / f".__import__{uuid.uuid4().hex}_{safe}"


def _convert_uploaded_archive(
    tasks_dir: Path, upl_name: str, raw: bytes
) -> "marcedit_import.ArchiveConversionResult":
    """Write the uploaded ``.task`` archive bytes to a traversal-safe scratch
    file inside ``tasks_dir``, convert it, and always remove the scratch file.
    """
    scratch = _archive_scratch_path(tasks_dir, upl_name)
    try:
        scratch.write_bytes(raw)
        return marcedit_import.convert_task_archive(scratch)
    finally:
        scratch.unlink(missing_ok=True)


def _do_marcedit_import(upl, tasks_dir: Path) -> None:
    """Parse a MarcEdit upload into session-scoped editable drafts."""
    _clear_marcedit_import_result()
    user = session.current_user_id()
    try:
        raw = upl.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.exception("MarcEdit upload read failed")
        _set_marcedit_import_result({
            "status": "rejected",
            "uploaded_filename": getattr(upl, "name", "upload"),
            "imported_task_names": [],
            "entries": [{
                "entry_name": getattr(upl, "name", "upload"),
                "status": "failed",
                "message": str(exc),
            }],
            "rejection_category": "unexpected",
        })
        audit_event(
            "tasksfile-rejected",
            user=user,
            filename=getattr(upl, "name", "upload"),
            size=0,
            reason="upload-read-exception",
            detail=f"{type(exc).__name__}: {exc}",
        )
        return
    is_archive = upl.name.lower().endswith(".task")
    # Tasksfiles are text → 1 MB cap. Archives can be larger because
    # they bundle multiple inner txt entries, but each inner entry is
    # gated again inside convert_task_archive.
    quota_kind = "upload" if is_archive else "tasksfile"
    try:
        quotas.check_upload(len(raw), kind=quota_kind)
    except quotas.QuotaExceeded as exc:
        _set_marcedit_import_result({
            "status": "rejected",
            "uploaded_filename": upl.name,
            "imported_task_names": [],
            "entries": [{
                "entry_name": upl.name,
                "status": "failed",
                "message": str(exc),
            }],
            "rejection_category": "quota",
        })
        audit_event(
            "tasksfile-rejected" if not is_archive else "archive-rejected",
            user=user,
            filename=upl.name,
            size=len(raw),
            reason=exc.kind,
            limit=exc.limit,
        )
        return

    try:
        if is_archive:
            archive = _convert_uploaded_archive(tasks_dir, upl.name, raw)
            if archive.archive_errors:
                _set_marcedit_import_result({
                    "status": "rejected",
                    "uploaded_filename": upl.name,
                    "imported_task_names": [],
                    "entries": [
                        {
                            "entry_name": upl.name,
                            "status": "failed",
                            "message": err,
                        }
                        for err in archive.archive_errors
                    ],
                    "rejection_category": "archive-validation",
                })
                audit_event(
                    "archive-rejected",
                    user=user,
                    filename=upl.name,
                    size=len(raw),
                    reason="archive-errors",
                    detail=archive.archive_errors[:3],
                )
                return
            entries: list[dict] = []
            for er in archive.entries:
                draft = getattr(er, "draft", None)
                if er.success and draft is not None:
                    entries.append(_draft_result_entry(
                        draft,
                        entry_name=er.entry_name,
                    ))
                elif er.error:
                    entries.append({
                        "entry_name": er.entry_name,
                        "status": "failed",
                        "message": er.error,
                    })
                else:
                    entries.append({
                        "entry_name": er.entry_name,
                        "status": "failed",
                        "message": "inner archive entry conversion failed",
                    })

            drafts = [
                entry for entry in entries
                if entry["status"] in {"draft_ready", "needs_review"}
            ]
            if (
                len(entries) == 1
                and len(drafts) == 1
                and drafts[0]["status"] == "draft_ready"
            ):
                _adopt_migration_draft(
                    drafts[0]["draft"],
                    entry_name=drafts[0].get("entry_name") or upl.name,
                    entry_key="0",
                )
                audit_event(
                    "archive-draft-opened",
                    user=user,
                    filename=upl.name,
                    size=len(raw),
                    entries=1,
                )
                return

            if not drafts:
                status = "rejected"
            elif any(entry["status"] != "draft_ready" for entry in entries):
                status = "partial"
            else:
                status = "success"
            category = "unexpected" if status == "rejected" else None
            _set_marcedit_import_result({
                "status": status,
                "uploaded_filename": upl.name,
                "imported_task_names": [],
                "entries": entries,
                "rejection_category": category,
            })
            audit_event(
                "archive-drafts-ready"
                if status != "rejected"
                else "archive-rejected",
                user=user,
                filename=upl.name,
                size=len(raw),
                drafts=len(drafts),
                entries=len(archive.entries),
            )
            return
        else:
            name = marcedit_import._derive_name_from_filename(upl.name)
            conv = marcedit_import.convert_tasksfile_text(
                raw.decode("utf-8"),
                name=name,
                description_fallback=f"Imported from {upl.name}",
                source_entry=upl.name,
            )
            if conv.draft is None:
                raise ValueError("task conversion did not produce an editable draft")
            if conv.draft.status == "needs_review":
                _set_marcedit_import_result({
                    "status": "partial",
                    "uploaded_filename": upl.name,
                    "imported_task_names": [],
                    "entries": [_draft_result_entry(
                        conv.draft,
                        entry_name=upl.name,
                    )],
                    "rejection_category": "unresolved-instructions",
                })
                audit_event(
                    "tasksfile-draft-needs-review",
                    user=user,
                    filename=upl.name,
                    size=len(raw),
                    blocking=conv.draft.summary.blocking,
                )
                return
            _adopt_migration_draft(
                conv.draft.to_session_dict(),
                entry_name=upl.name,
                entry_key="0",
            )
            audit_event(
                "tasksfile-draft-opened",
                user=user,
                filename=upl.name,
                size=len(raw),
                task_name=conv.name,
                converted=conv.draft.summary.converted,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("MarcEdit import failed")
        _set_marcedit_import_result({
            "status": "rejected",
            "uploaded_filename": upl.name,
            "imported_task_names": [],
            "entries": [{
                "entry_name": upl.name,
                "status": "failed",
                "message": str(exc),
            }],
            "rejection_category": "unexpected",
        })
        audit_event(
            "tasksfile-rejected" if not is_archive else "archive-rejected",
            user=user,
            filename=upl.name,
            size=len(raw),
            reason="exception",
            detail=f"{type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Task draft panel
# ---------------------------------------------------------------------------


def _render_ai_draft_panel() -> None:
    with st.expander("Draft task from notes"):
        gemini_enabled = gemini_task_draft.is_enabled()
        if not gemini_enabled:
            st.info(
                "Local note parsing is available. Set GEMINI_API_KEY to enable "
                "Gemini fallback for unresolved lines."
            )
        with st.expander("Supported note syntax", expanded=False):
            st.code(note_task_draft.help_text(), language="text")

        notes = st.text_area(
            "Cataloger notes",
            value=st.session_state.get(K_AI_DRAFT_NOTES, ""),
            key=K_AI_DRAFT_NOTES,
            height=160,
        )
        if st.button(
            "Draft task",
            key="tasks_ai_draft_btn",
            disabled=(not notes.strip()),
        ):
            try:
                review = note_task_draft.draft_task_from_notes(notes)
            except ai_task_draft.DraftValidationError as exc:
                _store_ai_draft_error(str(exc))
            else:
                _store_ai_draft_review(review)
                audit_event(
                    "ai-task-draft-created",
                    user=session.current_user_id(),
                    source="deterministic",
                    task_name=review.task_name,
                    accepted_operations=len(review.operations),
                    blocking_issues=ai_task_draft.blocking_issue_count(review),
                )
                st.rerun()

        if st.session_state.get(K_AI_DRAFT_ERROR):
            st.error(st.session_state[K_AI_DRAFT_ERROR])

        review = st.session_state.get(K_AI_DRAFT_REVIEW)
        if review is not None and _ai_fallback_available(review):
            if st.button(
                "Use Gemini for unresolved lines",
                key="tasks_gemini_fallback_btn",
            ):
                try:
                    gemini_review = gemini_task_draft.draft_task_from_notes(
                        note_task_draft.unresolved_text(review)
                    )
                except (
                    gemini_task_draft.GeminiTaskDraftError,
                    ai_task_draft.DraftValidationError,
                ) as exc:
                    _store_ai_draft_error(str(exc))
                else:
                    merged_review = note_task_draft.merge_fallback_review(
                        review, gemini_review
                    )
                    _store_ai_draft_review(merged_review)
                    audit_event(
                        "ai-task-draft-created",
                        user=session.current_user_id(),
                        source="gemini-fallback",
                        task_name=merged_review.task_name,
                        accepted_operations=len(merged_review.operations),
                        blocking_issues=ai_task_draft.blocking_issue_count(
                            merged_review
                        ),
                    )
                    st.rerun()


def _render_ai_draft_review() -> None:
    review = st.session_state[K_AI_DRAFT_REVIEW]
    blocking_issues = ai_task_draft.blocking_issue_count(review)
    st.subheader("Task draft review")
    st.markdown(f"**Proposed task:** `{review.task_name}`")
    description = _ai_draft_review_description(review)
    st.caption(description or "_No description proposed._")

    if review.operations:
        st.markdown("**Generated operations**")
        for index, op in enumerate(review.operations, start=1):
            st.markdown(f"{index}. {_ai_draft_operation_summary(op)}")
    else:
        st.info("No supported operations were generated.")

    _render_ai_draft_list("Manual notes", review.manual_notes)
    _render_ai_draft_list("Unsupported lines", review.unsupported_lines)
    _render_ai_draft_list("Questions", review.questions)

    if review.rejected_operations:
        st.markdown("**Rejected operations**")
        for rejected in review.rejected_operations:
            st.warning(_ai_draft_rejected_operation_summary(rejected))

    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = blocking_issues == 0
    if blocking_issues:
        st.warning(
            f"{blocking_issues} task draft issue(s) need review before this "
            "draft can be saved as a new task."
        )

    use_col, clear_col = st.columns([1, 1])
    if use_col.button(
        "Use this draft in form editor",
        key="tasks_ai_draft_use",
        type="primary",
        disabled=_ai_draft_handoff_disabled(review),
    ):
        _open_editor_for_ai_draft(review)
        st.rerun()
    if clear_col.button("Clear draft", key="tasks_ai_draft_clear"):
        _clear_ai_draft_review()
        st.rerun()


def _render_ai_draft_list(label: str, values: tuple[str, ...]) -> None:
    if not values:
        return
    st.markdown(f"**{label}**")
    for value in values:
        st.markdown(f"- {value}")


def _ai_draft_review_description(review: ai_task_draft.DraftReview) -> str:
    return review.description


def _ai_draft_operation_summary(op: ai_task_draft.DraftOperation) -> str:
    pieces = [f"`{op.kind}`"]
    if op.confidence:
        pieces.append(f"confidence: {op.confidence}")
    if op.explanation:
        pieces.append(op.explanation)

    detail = _ai_draft_operation_detail(op)
    if detail:
        pieces.append(detail)
    return " — ".join(pieces)


def _ai_draft_rejected_operation_summary(
    op: ai_task_draft.RejectedOperation,
) -> str:
    pieces = [f"`{op.kind or '(missing kind)'}`"]
    if op.reason:
        pieces.append(op.reason)
    if op.source_text:
        pieces.append(f"source: {op.source_text}")
    return " — ".join(pieces)


def _ai_draft_operation_detail(op: ai_task_draft.DraftOperation) -> str:
    params = op.params or {}
    regex = op.regex or {}
    parts = []
    for key in ("pattern", "meaning", "before", "after"):
        value = regex.get(key)
        if value is None:
            value = params.get(key)
        if value not in (None, ""):
            parts.append(f"{key}: {value}")
    return "; ".join(parts)


def _open_editor_for_ai_draft(review: ai_task_draft.DraftReview) -> None:
    current = st.session_state.get(K_WORKSPACE_LOCATION, WorkspaceLocation())
    _write_workspace_location(dataclasses.replace(current, view="create"))
    st.session_state[K_EDITOR_OPEN] = True
    st.session_state[K_EDITOR_MODE] = "form"
    st.session_state[K_EDITOR_NAME] = review.task_name
    description = _ai_draft_review_description(review)
    st.session_state[K_EDITOR_DESCRIPTION] = description
    _sync_editor_widget_inputs(review.task_name, description)
    st.session_state[K_EDITOR_BODY] = ""
    draft_ops = ai_task_draft.operations_for_editor(review)
    st.session_state[K_EDITOR_OPS] = (
        task_authoring.normalize_operations_for_editor(draft_ops)
    )
    st.session_state[K_EDITOR_ORIGINAL_NAME] = None
    st.session_state[K_EDITOR_ORIGINAL_OWNER] = None
    st.session_state[K_EDITOR_PRESERVE_BODY] = False
    st.session_state[K_EDITOR_VISIBILITY] = "private"
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = True
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = review
    _reset_operation_dialog_state()


def _ai_draft_save_blocked_for_new_task() -> bool:
    if not st.session_state.get(K_EDITOR_FROM_AI_DRAFT, False):
        return False
    review = st.session_state.get(K_EDITOR_AI_DRAFT_REVIEW)
    if review is None:
        return False
    if st.session_state.get(K_EDITOR_ORIGINAL_NAME) is not None:
        return False
    return ai_task_draft.blocking_issue_count(review) > 0


def _ai_draft_handoff_disabled(review: ai_task_draft.DraftReview) -> bool:
    return not review.operations


def _ai_fallback_available(review: ai_task_draft.DraftReview) -> bool:
    return (
        gemini_task_draft.is_enabled()
        and bool(note_task_draft.unresolved_text(review).strip())
    )


def _sync_editor_widget_inputs(name: str, description: str) -> None:
    st.session_state[K_EDITOR_NAME_INPUT] = name
    st.session_state[K_EDITOR_DESCRIPTION_INPUT] = description


def _clear_ai_draft_review() -> None:
    st.session_state[K_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False
    st.session_state[K_AI_DRAFT_ERROR] = None
    if st.session_state.get(K_EDITOR_FROM_AI_DRAFT, False):
        st.session_state[K_EDITOR_OPEN] = False
        st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
        st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None
        _reset_operation_dialog_state()


def _render_import_summary() -> None:
    summary = st.session_state.get(K_EDITOR_IMPORT_SUMMARY)
    if not isinstance(summary, dict):
        return
    converted = summary.get("converted", 0)
    blocking = summary.get("blocking", 0)
    total = summary.get("total", 0)
    source = st.session_state.get(K_EDITOR_IMPORT_SOURCE) or {}
    filename = source.get("entry_name") or source.get("description") or "the imported source"
    if blocking:
        st.warning(
            "Imported draft: {0} of {1} instructions converted; {2} need "
            "your confirmation before preview or execution.".format(
                converted,
                total,
                blocking,
            )
        )
    else:
        st.success(
            "Imported draft: {0} instructions converted and ready to edit.".format(
                converted
            )
        )
    disclosures = st.session_state.get(K_EDITOR_IMPORT_DISCLOSURES) or []
    if disclosures:
        st.caption("Open equivalent: " + " ".join(str(item) for item in disclosures))
    provenance = st.session_state.get(K_EDITOR_IMPORT_PROVENANCE) or []
    if provenance:
        with st.expander("Technical details"):
            st.caption("Source: " + str(filename))
            for item in provenance[:50]:
                st.code(
                    "line {0}: {1}".format(
                        item.get("line_number", "?"),
                        item.get("source_line", ""),
                    ),
                    language="text",
                )
            if len(provenance) > 50:
                st.caption(
                    "{0} additional source lines omitted.".format(
                        len(provenance) - 50
                    )
                )


def _store_ai_draft_error(message: str) -> None:
    st.session_state[K_AI_DRAFT_ERROR] = message
    st.session_state[K_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False


def _store_ai_draft_review(review: ai_task_draft.DraftReview) -> None:
    st.session_state[K_AI_DRAFT_REVIEW] = review
    st.session_state[K_AI_DRAFT_ERROR] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False


# ---------------------------------------------------------------------------
# Editor renderer (form + code)
# ---------------------------------------------------------------------------


def _render_editor(tasks_dir: Path, is_admin: bool) -> None:
    st.divider()
    is_edit = st.session_state[K_EDITOR_ORIGINAL_NAME] is not None
    st.subheader(
        f"Edit `{st.session_state[K_EDITOR_ORIGINAL_NAME]}`"
        if is_edit
        else "New task"
    )
    _render_import_summary()

    # Mode toggle: admins see it, standard users are pinned to form.
    if is_admin:
        mode = st.radio(
            "Editor mode",
            options=["form", "code"],
            index=0 if st.session_state[K_EDITOR_MODE] == "form" else 1,
            horizontal=True,
            key="tasks_editor_mode_radio",
            help=(
                "Code view writes raw Python; form view builds tasks from "
                "a typed operation palette. Both run through the subprocess "
                "sandbox at execution time."
            ),
        )
        st.session_state[K_EDITOR_MODE] = mode
    else:
        # Standard users are pinned to form view regardless of state.
        st.session_state[K_EDITOR_MODE] = "form"

    st.session_state.setdefault(
        K_EDITOR_NAME_INPUT,
        st.session_state[K_EDITOR_NAME],
    )
    st.session_state.setdefault(
        K_EDITOR_DESCRIPTION_INPUT,
        st.session_state[K_EDITOR_DESCRIPTION],
    )
    collaborator_edit = bool(
        is_edit
        and st.session_state.get(K_EDITOR_ORIGINAL_OWNER)
        and st.session_state[K_EDITOR_ORIGINAL_OWNER] != session.current_user_id()
    )
    st.session_state[K_EDITOR_NAME] = st.text_input(
        "Task name (lowercase, digits, hyphens)",
        help=(
            "Used in the @task(...) decorator. Must be unique."
            + (" Only the owner can rename a shared task." if collaborator_edit else "")
        ),
        key=K_EDITOR_NAME_INPUT,
        disabled=collaborator_edit,
    )
    st.session_state[K_EDITOR_DESCRIPTION] = st.text_input(
        "Description (one sentence)",
        key=K_EDITOR_DESCRIPTION_INPUT,
    )

    vis_default = st.session_state.get(K_EDITOR_VISIBILITY, "private")
    st.session_state[K_EDITOR_VISIBILITY] = st.radio(
        "Visibility",
        options=["private", "shared"],
        index=0 if vis_default == "private" else 1,
        horizontal=True,
        key="tasks_editor_visibility_radio",
        help=(
            "**Private** — only you see this task. "
            "**Shared** — every signed-in user can see and run it; "
            "only you can edit or delete."
        ),
    )

    if st.session_state[K_EDITOR_MODE] == "form":
        _render_form_editor()
    else:
        _render_code_editor()

    save_disabled = _ai_draft_save_blocked_for_new_task()
    if save_disabled:
        st.warning(
            "Resolve the blocking task draft review items before saving this "
            "new task."
        )

    save_col, cancel_col = st.columns([1, 1])
    save_col.button(
        "Save task",
        type="primary",
        key="tasks_save",
        on_click=_save_callback,
        args=(tasks_dir,),
        disabled=save_disabled,
    )
    cancel_col.button(
        "Cancel",
        key="tasks_cancel",
        on_click=_cancel_callback,
    )

    # Display any pending success/error from the last save attempt.
    if st.session_state.get(K_SAVE_ERROR):
        st.error(st.session_state.pop(K_SAVE_ERROR))
    if st.session_state.get(K_SAVE_SUCCESS):
        st.success(st.session_state.pop(K_SAVE_SUCCESS))


def _render_code_editor() -> None:
    st.caption(
        "Code view. Write the function **body only**. `record` is a "
        "`pymarc.Record`; import helpers from `marcedit_web.lib.transforms` "
        "as needed."
    )
    new_body = st_ace(
        value=st.session_state[K_EDITOR_BODY],
        language="python",
        theme="github",
        keybinding="vscode",
        font_size=13,
        tab_size=4,
        wrap=True,
        show_gutter=True,
        show_print_margin=False,
        auto_update=False,
        min_lines=10,
        key="tasks_editor_ace",
    )
    if new_body is not None:
        st.session_state[K_EDITOR_BODY] = new_body


def _next_operation_dialog_nonce() -> int:
    nonce = int(st.session_state.get(K_OPERATION_DIALOG_NONCE, 0)) + 1
    st.session_state[K_OPERATION_DIALOG_NONCE] = nonce
    return nonce


def _open_add_operation_dialog() -> None:
    st.session_state[K_OPERATION_DIALOG_STATE] = (
        task_operation_dialog.new_add_state(_next_operation_dialog_nonce())
    )


def _open_edit_operation_dialog(index: int) -> None:
    operations = st.session_state.get(K_EDITOR_OPS, [])
    if index < 0 or index >= len(operations):
        return
    st.session_state[K_OPERATION_DIALOG_STATE] = (
        task_operation_dialog.new_edit_state(
            operations[index],
            index=index,
            nonce=_next_operation_dialog_nonce(),
        )
    )


def _open_suggested_operation(index: int) -> None:
    operations = st.session_state.get(K_EDITOR_OPS, [])
    if index < 0 or index >= len(operations):
        return
    blocker = operations[index]
    suggested = task_operation_dialog.suggested_operation_for_blocker(
        blocker
    )
    if suggested is None:
        _open_edit_operation_dialog(index)
        return
    st.session_state[K_OPERATION_DIALOG_STATE] = (
        task_operation_dialog.new_suggestion_state(
            blocker,
            suggested,
            index=index,
            nonce=_next_operation_dialog_nonce(),
        )
    )


def _close_operation_dialog() -> None:
    st.session_state[K_OPERATION_DIALOG_STATE] = None


def _close_operation_reference_dialog() -> None:
    st.session_state[K_OPERATION_REFERENCE_REQUESTED] = False


def _replace_editor_operations(operations: list[dict]) -> None:
    st.session_state[K_EDITOR_OPS] = copy.deepcopy(operations)


def _change_editor_operations(operations: list[dict]) -> None:
    _replace_editor_operations(operations)
    st.rerun()


def _keep_dialog_operations(operations: list[dict]) -> None:
    _replace_editor_operations(operations)
    _close_operation_dialog()


def _render_form_editor() -> None:
    """Coordinate compact operation cards and at most one dialog wrapper."""
    st.caption(
        "Operations run in order against every record. Add or edit one in a "
        "focused dialog."
    )

    is_admin = task_admin.is_admin(session.current_user_id())
    operations = st.session_state.get(K_EDITOR_OPS, [])
    previews = st.session_state.setdefault(K_GUIDED_REPLACE_PREVIEWS, {})
    store = session.current_store()

    blocker_count = len(task_authoring.migration_blockers(operations))
    if blocker_count:
        st.warning(
            "Needs migration review — resolve {0} imported {1} before "
            "previewing or running this task.".format(
                blocker_count,
                "instruction" if blocker_count == 1 else "instructions",
            )
        )

    if not is_admin and any(
        operation.get("kind") == "custom" for operation in operations
    ):
        st.warning(
            "This task contains a **`custom`** op with raw Python. You're "
            "not an admin, so its code is shown read-only. Save will "
            "preserve the existing code unchanged; to edit it ask an "
            "admin or use a typed op above."
        )
    if st.session_state.get(K_EDITOR_PRESERVE_BODY, False):
        st.warning(
            "This task uses hand-written code that cannot be shown in the "
            "form editor. Save preserves the existing code; ask an admin to "
            "edit the code or recreate it with typed operations."
        )

    task_operation_cards.render_operation_cards(
        operations,
        store=store,
        previews=previews,
        on_edit=_open_edit_operation_dialog,
        on_change=_change_editor_operations,
        on_suggestion=_open_suggested_operation,
    )

    if isinstance(st.session_state.get(K_EDITOR_IMPORT_SUMMARY), dict):
        st.caption(
            "Optional shortcut: the full Smith RDA cleanup profile adds six "
            "additional operations and is not part of the imported source task."
        )
    if st.button(
        "Add full Smith RDA cleanup profile (6 operations)",
        key="tasks_add_smith_rda_profile",
        help=(
            "Adds material classification, 040 $e rda, 245 $h removal, "
            "300 abbreviation expansion, relator normalization, and "
            "260-to-264 promotion as six explicit editable operations."
        ),
    ):
        operations.extend(rda_operations.smith_profile_operations())
        st.session_state[K_EDITOR_OPS] = operations
        st.rerun()

    if st.button("+ Add operation", key="tasks_form_add_operation"):
        _open_add_operation_dialog()
    if st.button(
        "Browse operation reference",
        key="tasks_form_operation_reference",
    ):
        st.session_state[K_OPERATION_REFERENCE_REQUESTED] = True

    active_state = st.session_state.get(K_OPERATION_DIALOG_STATE)
    if active_state is not None:
        st.session_state[K_OPERATION_REFERENCE_REQUESTED] = False

    contract_error = task_operation_dialog.dialog_contract_error()
    if contract_error:
        st.error(contract_error)
        return

    if active_state is not None:
        task_operation_dialog.render_active_dialog(
            active_state,
            operations=st.session_state.get(K_EDITOR_OPS, []),
            is_admin=is_admin,
            store=store,
            previews=previews,
            on_keep=_keep_dialog_operations,
            on_close=_close_operation_dialog,
        )
    elif st.session_state.get(K_OPERATION_REFERENCE_REQUESTED, False):
        task_operation_reference.open_reference_dialog(
            include_custom=is_admin,
            on_close=_close_operation_reference_dialog,
        )


# ---------------------------------------------------------------------------
# Form input rendering
# ---------------------------------------------------------------------------


def _palette_entry(kind: str) -> dict | None:
    for entry in OPERATIONS_PALETTE:
        if entry["kind"] == kind:
            return entry
    return None


def _default_params_for(kind: str) -> dict:
    return task_operation_dialog.default_params_for(kind)


def _render_param_input(
    param: dict, params: dict, *, key_prefix: str, is_admin: bool = False
) -> None:
    task_operation_dialog.render_param_input(
        param,
        params,
        key_prefix=key_prefix,
        is_admin=is_admin,
    )


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def _save_callback(tasks_dir: Path) -> None:
    """on_click callback for Save. Runs BEFORE Streamlit's iteration phase
    so mutations of TASK_REGISTRY / session_state don't trip the
    dict-changed-size error in `_call_callbacks`.

    Writes the task to SQL via task_db, re-materializes the user's
    visible-task dir, and reloads the importer.
    """
    name = (st.session_state.get(K_EDITOR_NAME_INPUT)
            or st.session_state.get(K_EDITOR_NAME) or "").strip()
    description = (
        st.session_state.get(K_EDITOR_DESCRIPTION_INPUT)
        or st.session_state.get(K_EDITOR_DESCRIPTION)
        or ""
    ).strip()
    original = st.session_state.get(K_EDITOR_ORIGINAL_NAME)
    mode = st.session_state.get(K_EDITOR_MODE, "form")
    visibility = st.session_state.get(K_EDITOR_VISIBILITY, "private")
    user = session.current_user_id()
    original_owner = (
        st.session_state.get(K_EDITOR_ORIGINAL_OWNER) or user
    )
    needs_migration_review = False
    native_definition = None

    if _ai_draft_save_blocked_for_new_task():
        st.session_state[K_SAVE_ERROR] = (
            "Resolve the blocking task draft review items before saving this "
            "new task."
        )
        return

    original_row = None
    if original:
        original_row = task_db.get_task(original_owner, original)
        if original_row is None:
            st.session_state[K_SAVE_ERROR] = (
                "This task changed or was removed. Refresh the task list and "
                "reopen it before saving."
            )
            return

    try:
        if mode == "form" and st.session_state.get(K_EDITOR_PRESERVE_BODY, False):
            raw_ops = st.session_state.get(K_EDITOR_OPS, [])
            if raw_ops:
                raise ValueError(
                    "This hand-written task cannot combine typed operations "
                    "with preserved code; ask an admin to recreate it first."
                )
            body = original_row["body"] if original_row else ""
            extra_imports = [
                line
                for line in (original_row.get("extra_imports") or "").split("\n")
                if line
            ] or None
        elif mode == "form":
            raw_ops = st.session_state.get(K_EDITOR_OPS, [])
            validation_errors = task_authoring.validate_operations(raw_ops)
            if validation_errors:
                raise ValueError("\n".join(validation_errors))
            needs_migration_review = bool(
                task_authoring.migration_blockers(raw_ops)
            )
            ops = [
                Operation.from_dict(
                    task_authoring.normalize_operation(op)
                    if op.get("kind") == "migration-blocker"
                    else op
                )
                for op in raw_ops
            ]
            rendered = task_builder.render_ops_to_python(ops)
            body = rendered["body"]
            extra_imports = rendered["imports"]
        else:
            if original_row and original_row.get("definition_json") is not None:
                raise ValueError(
                    "Native task definitions must be edited in form view."
                )
            body = st.session_state.get(K_EDITOR_BODY, "")
            extra_imports = None

        if (
            original_row
            and original_row.get("definition_json") is not None
            and mode == "form"
        ):
            native_definition = native_tasks.definition_from_editor_operations(
                native_tasks.load_definition_json(original_row["definition_json"]),
                name=name,
                description=description,
                operations=[
                    task_authoring.normalize_operation(op)
                    for op in st.session_state.get(K_EDITOR_OPS, [])
                ],
            )

        # Pre-flight: compile the to-be-saved file before we hit SQL, so
        # a syntax error keeps the existing row intact.
        preview = editor.serialize_user_task(
            name, description, body, extra_imports=extra_imports,
        )
        compile(preview, f"<{name}>", "exec")
    except (ValueError, SyntaxError) as exc:
        st.session_state[K_SAVE_ERROR] = (
            str(exc) if isinstance(exc, ValueError)
            else f"task code has a syntax error: {exc.msg} (line {exc.lineno})"
        )
        return

    try:
        if native_definition is not None:
            task_db.save_native_task(
                owner=original_owner,
                actor=user,
                definition=native_definition,
                visibility=visibility,
                task_id=original_row["id"],
                expected_revision=original_row["revision"],
            )
        else:
            task_db.save_task(
                owner=original_owner if original_row else user,
                actor=user,
                name=name,
                description=description,
                body=body,
                extra_imports=extra_imports,
                visibility=visibility,
                task_id=original_row["id"] if original_row else None,
                expected_revision=(
                    original_row["revision"] if original_row else None
                ),
            )
    except (ValueError, task_db.NativeTaskStorageError) as exc:
        st.session_state[K_SAVE_ERROR] = str(exc)
        return

    if original and original != name:
        tasks.TASK_REGISTRY.pop(original, None)
    tasks.TASK_REGISTRY.pop(name, None)
    # Re-materialize and reload so the running registry matches SQL.
    task_db.materialize_to_dir(user, tasks_dir)
    tasks.load_user_tasks(tasks_dir, force_reload=True)
    st.session_state[K_EDITOR_OPEN] = False
    st.session_state[K_EDITOR_ORIGINAL_OWNER] = None
    st.session_state[K_EDITOR_PRESERVE_BODY] = False
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_REVIEW] = None
    st.session_state[K_AI_DRAFT_BLOCKING_ACK] = False
    _reset_operation_dialog_state()
    st.session_state[K_SAVE_SUCCESS] = (
        f"Saved `{name}`. Needs migration review."
        if needs_migration_review
        else f"Saved `{name}`."
    )
    is_admin = task_admin.is_admin(user)
    audit_event(
        "task-saved",
        user=user,
        task_name=name,
        original=original,
        mode=mode,
        visibility=visibility,
        is_admin=is_admin,
        body_bytes=len(body or ""),
        owner_email=original_owner if original_row else user,
        collaborative_edit=bool(
            original_row
            and original_row["owner_email"] != user
            and original_row["visibility"] == "shared"
        ),
    )
    if mode == "code" and is_admin:
        # Admin Code-view save is the highest-trust path — surfaces a
        # second audit line so ops can filter on `admin-action` alone.
        audit_event(
            "admin-action",
            user=user,
            action="code-view-save",
            task_name=name,
        )


def _cancel_callback() -> None:
    """on_click callback for Cancel. Mirrors the on_click pattern of Save."""
    st.session_state[K_EDITOR_OPEN] = False
    st.session_state[K_EDITOR_ORIGINAL_OWNER] = None
    st.session_state[K_EDITOR_PRESERVE_BODY] = False
    st.session_state[K_EDITOR_FROM_AI_DRAFT] = False
    st.session_state[K_EDITOR_AI_DRAFT_REVIEW] = None
    _reset_operation_dialog_state()


# ---------------------------------------------------------------------------
# Run flow (sandbox)
# ---------------------------------------------------------------------------


def _render_run_panel(registered, tasks_dir: Path) -> None:
    available_names = [t.name for t in registered]
    selection = st.multiselect(
        "Tasks to run (applied in the listed order)",
        options=available_names,
        default=available_names[:1],
        help=(
            "Each task gets the same record one at a time; tasks later "
            "in the list see the output of earlier tasks. Execution "
            "happens in order in a bounded sandbox subprocess. Keep this "
            "tab open until the result is ready."
        ),
        key="tasks_run_selection",
    )
    st.caption(
        "Saved-task runs execute synchronously in a bounded sandbox. "
        "Keep this tab open while it runs; the result stays here for review "
        "before you download or apply it."
    )
    if st.button(
        "Run selected tasks",
        type="primary",
        disabled=not selection,
        key="tasks_run_btn",
    ):
        _execute_synchronous_run(selection, tasks_dir)


def _execute_synchronous_run(selection: list[str], tasks_dir: Path) -> None:
    """Run selected saved tasks without creating a durable operation row."""
    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload one on Home first.")
        return

    specs: list[sandbox.TaskSpec] = []
    raw_guided_operations: list[dict] = []
    for name in selection:
        try:
            parsed = editor.parse_user_task_file(
                editor.task_file_path(tasks_dir, name)
            )
        except (ValueError, FileNotFoundError) as exc:
            st.error(f"Could not load task `{name}`: {exc}")
            return
        preflight_issues = task_authoring.submission_preflight_issues(
            parsed["body"]
        )
        if preflight_issues:
            st.error(
                f"Task `{name}` cannot run until this saved instruction is "
                f"resolved: {preflight_issues[0]}"
            )
            return
        parsed_ops = task_builder.parse_ops_from_source(parsed["body"])
        if parsed_ops["form_editable"]:
            raw_guided_operations.extend(
                op.to_dict()
                for op in parsed_ops["ops"]
                if (
                    op.kind == "guided-find-replace"
                    and op.params.get("match_mode") == "raw_regex"
                )
            )
        specs.append(sandbox.TaskSpec(name=name, body=parsed["body"], imports=[]))

    if raw_guided_operations:
        previews = st.session_state.get(K_GUIDED_REPLACE_PREVIEWS, {})
        for operation in raw_guided_operations:
            try:
                cache_key = guided_replace_preview.preview_cache_key(operation)
            except (TypeError, ValueError) as exc:
                st.error(str(exc))
                return
            preview = previews.get(cache_key)
            if (
                preview is None
                or not guided_replace_preview.is_current(
                    preview, store, operation
                )
            ):
                st.error(
                    "Preview this raw regular expression successfully "
                    "against the current loaded file before running it."
                )
                return

    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-sync-"))
    input_path = workdir / "input.mrc"
    with st.status("Running tasks…", expanded=True) as status:
        st.write(f"Reading **{store.count():,}** records from upload")
        store.write_mrc_to(input_path)
        st.write(
            f"Running {len(specs)} task(s) in the sandbox: "
            + ", ".join(f"`{spec.name}`" for spec in specs)
        )
        try:
            with _batch_operation("saved-task", phase="sandbox", store=store) as measurement:
                sync_run = synchronous_task_runner.run_tasks(
                    input_path, specs, tmp_dir=workdir
                )
                result = sync_run.result
                if result.timed_out:
                    measurement.mark_error("SandboxTimeout")
                elif result.returncode != 0:
                    measurement.mark_error("SandboxNonzeroExit")
        except Exception as exc:  # noqa: BLE001 - show bounded user action
            logger.exception("synchronous saved-task run failed")
            status.update(label="Task run failed", state="error", expanded=False)
            st.error(f"Task run failed before producing an output: {exc}")
            shutil.rmtree(workdir, ignore_errors=True)
            return
        if result.timed_out:
            status.update(label="Sandbox timed out", state="error", expanded=False)
        elif result.returncode != 0:
            status.update(
                label=f"Sandbox exited with code {result.returncode}",
                state="error",
                expanded=False,
            )
        else:
            status.update(
                label="Done — review the result below",
                state="complete",
                expanded=False,
            )

    try:
        with result.output_path.open("rb") as output_fh:
            output_count = sum(
                record is not None
                for record in pymarc.MARCReader(
                    output_fh, to_unicode=True, permissive=True
                )
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse sandbox output: {exc}")
        output_count = 0

    diff_summary = None
    if result.returncode == 0 and not result.timed_out:
        try:
            diff_summary = task_diff.compute_task_diff(
                input_path, result.output_path
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not build task diff summary: %s", exc)

    user = session.current_user_id()
    summary = {
        "task_names": list(selection),
        "input_record_count": store.count(),
        "output_record_count": output_count,
        "changed_count": diff_summary.changed_count if diff_summary else 0,
        "error_count": result.error_count,
        "timed_out": bool(result.timed_out),
        "sandbox_returncode": int(result.returncode or 0),
    }
    snapshot = None
    if not result.timed_out and not _uses_job_file_versions():
        snapshot = snapshot_actions.record_job_snapshot(
            job_id=st.session_state.get("current_job_id"),
            user_email=user,
            kind="task-run",
            label=", ".join(selection) or "Task run",
            before_path=input_path,
            after_path=result.output_path,
            summary=summary,
        )
    if snapshot is not None:
        audit_event(
            "job-snapshot-created",
            user=user,
            snapshot_id=snapshot["id"],
            job_id=snapshot["job_id"],
            snapshot_kind=snapshot["kind"],
        )
    audit_event(
        "task-run-completed",
        user=user,
        tasks=list(selection),
        input_records=store.count(),
        output_records=output_count,
        changed_count=summary["changed_count"],
        error_count=result.error_count,
        timed_out=bool(result.timed_out),
        returncode=int(result.returncode or 0),
    )
    st.session_state[K_SYNC_RUN_RESULT] = {
        "task_names": list(selection),
        "input_count": store.count(),
        "output_count": output_count,
        "error_count": result.error_count,
        "errors": list(result.errors),
        "timed_out": bool(result.timed_out),
        "returncode": int(result.returncode or 0),
        "stderr": result.stderr,
        "input_path": str(input_path),
        "output_path": str(result.output_path),
        "workdir": str(workdir),
        "diff_summary": diff_summary,
        "snapshot_id": snapshot["id"] if snapshot is not None else None,
        "filename": _export_filename(session.current_filename(), "tasks"),
        "preview_version_id": (
            st.session_state.get("job_file_version_id")
            if _uses_job_file_versions() else None
        ),
        "summary": summary,
    }


def _render_sync_run_result() -> None:
    """Review and export/apply the last synchronous sandbox result."""
    result = st.session_state.get(K_SYNC_RUN_RESULT)
    if not result:
        return
    st.divider()
    st.markdown("**Task run result**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Records in", result["input_count"])
    c2.metric("Records out", result["output_count"])
    c3.metric("Errors", result["error_count"])
    st.caption("Tasks applied: " + ", ".join(f"`{n}`" for n in result["task_names"]))
    if result["timed_out"]:
        st.error("The sandbox time limit was reached. No output was applied.")
    elif result["returncode"] != 0:
        st.warning(
            f"Sandbox exited with code {result['returncode']}. Review the "
            "diagnostics before retrying."
        )
    if result["stderr"]:
        with st.expander("Technical diagnostics", expanded=False):
            st.code(result["stderr"][:sandbox.MAX_STDERR_BYTES], language="text")
    if result["errors"]:
        with st.expander(f"Record errors ({result['error_count']:,})", expanded=False):
            st.dataframe(pd.DataFrame(result["errors"]), hide_index=True, use_container_width=True)
    diff_summary = result.get("diff_summary")
    if diff_summary is not None:
        st.metric("Changed records", diff_summary.changed_count)
        _render_per_tag_summary_table(diff_summary)
        if diff_summary.per_record_diffs:
            with st.expander("Show representative record changes", expanded=False):
                _render_per_record_diffs(diff_summary)
    if result["timed_out"] or result["returncode"] != 0:
        return
    if _uses_job_file_versions():
        if st.button("Apply as new version", type="primary", key="tasks_sync_apply"):
            if result.get("preview_version_id") != st.session_state.get("job_file_version_id"):
                st.error("File changed since this result was created. Run the task again.")
            else:
                try:
                    with _owned_candidate(Path(result["output_path"]), prefix="marcedit-web-task-apply-") as candidate:
                        version = session.adopt_current_candidate(
                            candidate_path=candidate,
                            source_kind="task",
                            label=", ".join(result["task_names"]),
                            summary=result["summary"],
                            validation={"error_count": result["error_count"]},
                        )
                except (
                    job_files.JobFileError,
                    collaboration.CollaborationError,
                    OSError,
                ) as exc:
                    st.error(str(exc))
                else:
                    st.success(f"Applied as version {version['version_number']}.")
                    shutil.rmtree(result["workdir"], ignore_errors=True)
                    st.session_state[K_SYNC_RUN_RESULT] = None
                    return
    st.caption("The updated MARC is ready as a separate download.")
    _offer_history_download(
        st,
        result["output_path"],
        f"Download {result['filename']}",
        result["filename"],
        key="tasks_sync_download",
    )


def _submit_queued_run(selection: list[str], tasks_dir: Path) -> None:
    """Snapshot selected task definitions and submit one durable operation."""
    specs: list[sandbox.TaskSpec] = []
    raw_guided_operations = []
    for name in selection:
        try:
            parsed = editor.parse_user_task_file(
                editor.task_file_path(tasks_dir, name)
            )
        except (ValueError, FileNotFoundError) as exc:
            st.error(f"Could not load task `{name}`: {exc}")
            return
        preflight_issues = task_authoring.submission_preflight_issues(
            parsed["body"]
        )
        if preflight_issues:
            st.error(
                "Task `{0}` cannot run until this saved instruction is "
                "resolved: {1}".format(name, preflight_issues[0])
            )
            return
        parsed_ops = task_builder.parse_ops_from_source(parsed["body"])
        if parsed_ops["form_editable"]:
            raw_guided_operations.extend(
                op.to_dict()
                for op in parsed_ops["ops"]
                if (
                    op.kind == "guided-find-replace"
                    and op.params.get("match_mode") == "raw_regex"
                )
            )
        specs.append(sandbox.TaskSpec(
            name=name,
            body=parsed["body"],
            imports=[],
        ))

    if raw_guided_operations:
        store = session.current_store()
        previews = st.session_state.get(K_GUIDED_REPLACE_PREVIEWS, {})
        for operation in raw_guided_operations:
            try:
                cache_key = guided_replace_preview.preview_cache_key(
                    operation
                )
            except (TypeError, ValueError) as exc:
                st.error(str(exc))
                return
            preview = previews.get(cache_key)
            if (
                store is None
                or preview is None
                or not guided_replace_preview.is_current(
                    preview, store, operation
                )
            ):
                st.error(
                    "Preview this raw regular expression successfully "
                    "against the current loaded file before submitting it."
                )
                return

    user = session.current_user_id()
    try:
        if _uses_job_file_versions():
            source_version_id = st.session_state.get("job_file_version_id")
            if source_version_id is None:
                st.error("Open a Job file version before queuing tasks.")
                return
            created = operation_submission.submit_job_task_run(
                user_email=user,
                file_id=int(st.session_state["job_file_id"]),
                source_version_id=int(source_version_id),
                task_specs=specs,
            )
        else:
            store = session.current_store()
            if store is None:
                st.error("No loaded batch — upload one on Home first.")
                return
            created = operation_submission.submit_quick_load_task_run(
                user_email=user,
                source_path=store.path,
                filename=session.current_filename() or "quick-load.mrc",
                record_count=store.count(),
                task_specs=specs,
            )
    except ValueError as exc:
        st.error(str(exc))
        return

    operation_id = int(created["id"])
    st.success("Operation queued. You can safely leave this page.")
    st.page_link(
        "views/D_Operations.py",
        label=f"View operation {operation_id}",
        icon=":material/pending_actions:",
    )


def _render_per_tag_summary_table(summary: task_diff.TaskDiffSummary) -> None:
    """Tag / Added / Deleted / Modified rollup table."""
    tags = sorted(
        set(summary.per_tag_added)
        | set(summary.per_tag_deleted)
        | set(summary.per_tag_modified)
    )
    if not tags:
        return
    df = pd.DataFrame(
        [
            {
                "Tag": t,
                "Added": summary.per_tag_added.get(t, 0),
                "Deleted": summary.per_tag_deleted.get(t, 0),
                "Modified": summary.per_tag_modified.get(t, 0),
            }
            for t in tags
        ]
    )
    st.dataframe(df, hide_index=True, use_container_width=True)


_DIFF_PAGE_KEY = "tasks_diff_page"
_DIFF_PER_PAGE = 5


def _render_per_record_diffs(summary: task_diff.TaskDiffSummary) -> None:
    """Paginated side-by-side per-record diff cards."""
    diffs = summary.per_record_diffs
    total = len(diffs)
    pages = max(1, (total + _DIFF_PER_PAGE - 1) // _DIFF_PER_PAGE)
    page = st.session_state.get(_DIFF_PAGE_KEY, 0)
    page = max(0, min(page, pages - 1))

    nav_a, nav_b, nav_c = st.columns([1, 2, 1])
    if nav_a.button("◀ Prev", key="tasks_diff_prev", disabled=page == 0):
        st.session_state[_DIFF_PAGE_KEY] = page - 1
        st.rerun()
    nav_b.caption(f"Page {page + 1} of {pages} — {total} changed records")
    if nav_c.button("Next ▶", key="tasks_diff_next", disabled=page >= pages - 1):
        st.session_state[_DIFF_PAGE_KEY] = page + 1
        st.rerun()

    start = page * _DIFF_PER_PAGE
    end = min(total, start + _DIFF_PER_PAGE)
    for diff in diffs[start:end]:
        st.markdown(
            f"**Record {diff.record_index + 1}** "
            + (f"— `001 = {diff.identifier}`" if diff.identifier else "")
        )
        _render_diff_rows(diff.rows)
        st.divider()


_STATUS_SYMBOL = {
    "unchanged": "  ",
    "added":     "+ ",
    "removed":   "- ",
    "changed":   "~ ",
}


def _render_diff_rows(
    rows: list[tuple[str, str, "marc_diff.DiffStatus"]],  # noqa: F821
) -> None:
    """Side-by-side rendering of one record's aligned diff.

    Uses a code block per side to preserve monospaced field-line
    alignment. Status markers (+, -, ~, " ") on each line make
    skim-reading easy without needing colors.
    """
    left_lines: list[str] = []
    right_lines: list[str] = []
    for old, new, status in rows:
        sym = _STATUS_SYMBOL[status]
        # Show the symbol on the side(s) where it makes sense.
        left_lines.append(
            f"{sym if status in ('removed', 'changed') else '  '}{old}"
        )
        right_lines.append(
            f"{sym if status in ('added', 'changed') else '  '}{new}"
        )
    col_old, col_new = st.columns(2)
    col_old.caption("Before")
    col_old.code("\n".join(left_lines), language="text")
    col_new.caption("After")
    col_new.code("\n".join(right_lines), language="text")


def _stamped_filename(orig: str | None) -> str:
    return _export_filename(orig, "transformed")


def _export_filename(orig: str | None, operation: str) -> str:
    if not orig:
        return session.stamped_filename(f"transformed_{operation}")
    p = Path(orig)
    return session.stamped_filename(f"{p.stem}_{operation}", p.suffix or ".mrc")


def _disk_backed_export(
    *,
    filename: str,
    source_path: Path,
    snapshot: dict | None,
    job_file_version: dict | None = None,
    prefix: str,
) -> dict:
    snapshot_path = snapshot.get("after_path") if snapshot else None
    if snapshot_path and Path(snapshot_path).exists():
        path = Path(snapshot_path)
        temporary_dir = None
        temporary = False
    else:
        export_dir = Path(tempfile.mkdtemp(prefix=prefix))
        path = export_dir / filename
        shutil.copyfile(source_path, path)
        temporary_dir = str(export_dir)
        temporary = True
    return {
        "filename": filename,
        "path": str(path),
        "temporary": temporary,
        "temporary_dir": temporary_dir,
        "snapshot_id": snapshot["id"] if snapshot is not None else None,
        "job_file_version_id": (
            job_file_version["id"] if job_file_version is not None else None
        ),
    }


def _cleanup_disk_backed_export(export: dict | None) -> None:
    if not export or not export.get("temporary"):
        return
    path_str = export.get("path")
    if path_str:
        try:
            Path(path_str).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not remove temporary export file: %s", exc)
    temp_dir = export.get("temporary_dir")
    if temp_dir:
        try:
            Path(temp_dir).rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# TASK-036: Quick find/replace wizard
# ---------------------------------------------------------------------------


_K_BR_PREVIEW = "batch_replace_preview"


def _render_quick_find_replace() -> None:
    """Render the one-shot find/replace wizard.

    Mounted below the saved-tasks run panel. Cataloger fills the
    form, clicks Preview, reviews the diff, clicks Apply.
    The wizard never persists a task file; the body lives only
    inside the sandbox driver's exec call.
    """
    if not session.has_upload():
        return  # nothing to find against

    with st.expander("✨ Quick find/replace", expanded=True):
        st.caption(
            "Run a one-shot find/replace across the loaded batch. "
            "Preview first; apply after you've reviewed the diff. "
            "Nothing is saved to your task list."
        )

        c1, c2 = st.columns([2, 1])
        tag = c1.text_input(
            "Tag (required)",
            value=st.session_state.get("br_tag", ""),
            max_chars=3,
            placeholder="245",
            key="br_tag",
        )
        subfield = c2.text_input(
            "Subfield (optional)",
            value=st.session_state.get("br_subfield", ""),
            max_chars=1,
            placeholder="a",
            help=(
                "Restrict the replace to one subfield code. Leave blank "
                "to replace across every subfield value of the tag."
            ),
            key="br_subfield",
        )

        find_text = st.text_input(
            "Find",
            value=st.session_state.get("br_find", ""),
            key="br_find",
        )
        replace_text = st.text_input(
            "Replace with",
            value=st.session_state.get("br_replace", ""),
            key="br_replace",
        )

        opt_a, opt_b = st.columns(2)
        regex = opt_a.checkbox(
            "Treat Find as regex",
            value=st.session_state.get("br_regex", False),
            key="br_regex",
        )
        ignore_case = opt_b.checkbox(
            "Case-insensitive",
            value=st.session_state.get("br_ignore_case", False),
            key="br_ignore_case",
        )

        request = BatchReplaceRequest(
            tag=(tag or "").strip(),
            subfield=(subfield or None) or None,
            find=find_text or "",
            replace=replace_text or "",
            regex=bool(regex),
            ignore_case=bool(ignore_case),
        )

        btn_preview, btn_reset, _ = st.columns([1, 1, 4])
        if btn_preview.button(
            "Preview", type="primary", key="br_preview_btn",
        ):
            _build_and_store_preview(request)
        if btn_reset.button("Reset", key="br_reset_btn"):
            batch_replace.cleanup_preview(
                st.session_state.pop(_K_BR_PREVIEW, None)
            )
            st.rerun()

        preview = st.session_state.get(_K_BR_PREVIEW)
        if preview is not None:
            _render_quick_preview(preview)


def _build_and_store_preview(request: BatchReplaceRequest) -> None:
    """Validate, run the sandbox preview, stash the result in session_state."""
    err = batch_replace.validate_request(request)
    if err:
        st.error(err)
        return

    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload a `.mrc` on Home first.")
        return

    with st.spinner("Building preview…"):
        try:
            with _batch_operation(
                "quick-replace", phase="preview", store=store
            ) as measurement:
                preview = batch_replace.build_preview(store, request)
                if preview.error:
                    measurement.mark_error("PreviewError")
        except ValueError as exc:
            st.error(str(exc))
            return

    quick_batch.cleanup_preview(st.session_state.pop(_K_QB_PREVIEW, None))
    batch_replace.cleanup_preview(st.session_state.get(_K_BR_PREVIEW))
    st.session_state[_K_BR_PREVIEW] = preview


def _render_quick_preview(preview) -> None:
    st.divider()
    if preview.error:
        st.error(preview.error)
        return
    if preview.is_empty:
        st.info(
            f"No records matched the find criteria "
            f"(tag={preview.request.tag!r}, "
            f"subfield={preview.request.subfield!r}, "
            f"find={preview.request.find!r})."
        )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Matched", preview.matched_count)
    c2.metric("Changed (in preview)", preview.changed_count)
    c3.metric(
        "Previewed records",
        preview.previewed_count,
    )

    if preview.preview_cap_triggered:
        st.info(
            f"Sandbox preview ran against the first "
            f"**{preview.previewed_count:,}** of "
            f"**{preview.matched_count:,}** matched records. "
            "Apply will run a fresh sandbox over the full matched set "
            "before committing — review the diff below to spot-check "
            "what the transform does."
        )

    if preview.diff_summary is not None and preview.diff_summary.per_record_diffs:
        # Reuse the existing per-tag rollup + per-record drill-down
        # used by the saved-task run results so the cataloger sees a
        # familiar review surface.
        _render_per_tag_summary_table(preview.diff_summary)
        with st.expander(
            f"Show per-record diffs ({preview.changed_count} changed records)",
            expanded=False,
        ):
            _render_per_record_diffs(preview.diff_summary)

    apply_col, _, _ = st.columns([1, 1, 4])
    if apply_col.button(
        "Apply to batch", type="primary", key="br_apply_btn",
    ):
        _apply_quick_preview(preview)


def _apply_quick_preview(preview) -> None:
    """Run apply, audit, refresh derived caches."""
    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload one on Home first.")
        return
    if _uses_job_file_versions():
        try:
            result, version = _adopt_quick_replace_preview(store, preview)
        except (job_files.JobFileError, collaboration.CollaborationError) as exc:
            st.error(str(exc))
            return
        snapshot = None
        user = session.current_user_id()
    else:
        version = None
        with snapshot_actions.staged_store_path(store) as before_path:
            with _batch_operation(
                "quick-replace", phase="apply", store=store
            ) as measurement:
                result = batch_replace.apply_preview(store, preview)
                if result.error:
                    measurement.mark_error("ApplyError")
            if result.error:
                st.error(result.error)
                return

            user = session.current_user_id()
            try:
                # Non-job Quick Load compatibility boundary: legacy history only.
                snapshot = snapshot_actions.record_job_snapshot(
                    job_id=st.session_state.get("current_job_id"),
                    user_email=user,
                    kind="quick-replace",
                    label=_quick_replace_label(preview),
                    before_path=before_path,
                    after_path=store.path,
                    summary={
                        "matched_count": preview.matched_count,
                        "changed_count": preview.changed_count,
                        "applied_count": result.applied_count,
                    },
                )
            except Exception:  # noqa: BLE001 — legacy history is best-effort
                logger.exception("quick find/replace snapshot failed")
                snapshot = None
                st.warning(
                    "Change applied, but recording the history snapshot failed."
                )
    if result.error:
        st.error(result.error)
        return
    if snapshot is not None:
        audit_event(
            "job-snapshot-created",
            user=user,
            snapshot_id=snapshot["id"],
            job_id=snapshot["job_id"],
            snapshot_kind=snapshot["kind"],
        )

    audit_event(
        "batch-replace-applied",
        user=user,
        filename=session.current_filename(),
        tag=preview.request.tag,
        subfield=preview.request.subfield,
        regex=preview.request.regex,
        ignore_case=preview.request.ignore_case,
        matched_count=preview.matched_count,
        changed_count=preview.changed_count,
        applied_count=result.applied_count,
    )
    # Stale derived state — Validate / Report / etc. cached the
    # pre-apply numbers.
    st.session_state["issues_cache"] = {}
    batch_replace.cleanup_preview(st.session_state.pop(_K_BR_PREVIEW, None))
    message = f"Applied to {result.applied_count} record(s)"
    if version is not None:
        message += f" as version {version['version_number']}"
    st.success(message + ". Other records are unchanged.")
    st.rerun()


def _quick_replace_label(preview) -> str:
    label = f"Find/replace {preview.request.tag}"
    if preview.request.subfield:
        label += f"${preview.request.subfield}"
    return label


def _adopt_quick_replace_preview(store, preview):
    if (
        preview.store_id != id(store)
        or preview.store_revision != store.revision
    ):
        return batch_replace.BatchReplaceResult(
            error="Batch changed since preview."
        ), None
    with snapshot_actions.staged_store_path(store) as candidate_path:
        candidate_store = RecordStore.from_path(candidate_path)
        candidate_preview = copy.copy(preview)
        candidate_preview.store_id = id(candidate_store)
        candidate_preview.store_revision = candidate_store.revision
        with _batch_operation(
            "quick-replace", phase="apply", store=candidate_store
        ) as measurement:
            result = batch_replace.apply_preview(candidate_store, candidate_preview)
            if result.error:
                measurement.mark_error("ApplyError")
        if result.error:
            return result, None
        version = session.adopt_current_candidate(
            candidate_path=candidate_path,
            source_kind="quick-replace",
            label=_quick_replace_label(preview),
            summary={
                "matched_count": preview.matched_count,
                "changed_count": preview.changed_count,
                "applied_count": result.applied_count,
            },
        )
    return result, version


# ---------------------------------------------------------------------------
# TASK-137: Quick batch operation wizard
# ---------------------------------------------------------------------------


_K_QB_PREVIEW = "quick_batch_preview"
_K_QB_EXPORT = "quick_batch_export"

_QB_OPERATION_LABELS = {
    "sort-fields": "Reorder fields by canonical tag order",
    "leader": "Leader value",
    "008-form": "008 form of item",
    "040-cleanup": "040 cleanup",
    "856-url": "856 URL tools",
    "035-oclc": "OCLC 035 cleanup",
    "9xx-delete": "Local 9xx cleanup",
    "655-cleanup": "655 genre/form cleanup",
}

_QB_856_ACTION_LABELS = {
    "add-proxy": "Add proxy prefix",
    "remove-proxy": "Remove proxy prefix",
    "delete-matching": "Delete 856 fields by URL text",
}


def _render_quick_batch_operations() -> None:
    """Render one-shot canned MARC cleanup operations."""
    if not session.has_upload():
        return

    st.divider()
    with st.expander("Quick batch operations", expanded=True):
        st.caption(
            "Run a structured cleanup across the loaded batch. Preview first; "
            "nothing is saved to your task list."
        )
        kind = st.selectbox(
            "Operation",
            options=list(_QB_OPERATION_LABELS),
            format_func=lambda value: _QB_OPERATION_LABELS.get(value, value),
            key="qb_kind",
        )
        request = _quick_batch_request_from_widgets(kind)

        btn_preview, btn_reset, _ = st.columns([1, 1, 4])
        if btn_preview.button("Preview", type="primary", key="qb_preview_btn"):
            _build_and_store_quick_batch_preview(request)
        if btn_reset.button("Reset", key="qb_reset_btn"):
            st.session_state.pop(_K_QB_PREVIEW, None)
            st.rerun()

        preview = st.session_state.get(_K_QB_PREVIEW)
        if preview is not None:
            _render_quick_batch_preview(preview)
        _render_quick_batch_export()


def _quick_batch_request_from_widgets(kind: str) -> QuickBatchRequest:
    if kind == "leader":
        positions = list(quick_batch.LEADER_OPTIONS)
        position = st.selectbox(
            "Leader position",
            options=positions,
            format_func=_format_leader_position,
            key="qb_leader_position",
        )
        options = quick_batch.LEADER_OPTIONS[position]
        value = st.selectbox(
            "Value",
            options=[option.value for option in options],
            format_func=lambda code: _format_code_option(code, options),
            key="qb_leader_value",
        )
        return QuickBatchRequest(kind=kind, position=position, value=value)

    if kind == "008-form":
        value = st.selectbox(
            "Form of item",
            options=[option.value for option in quick_batch.FORM_OF_ITEM_OPTIONS],
            format_func=lambda code: _format_code_option(
                code,
                quick_batch.FORM_OF_ITEM_OPTIONS,
            ),
            key="qb_008_form",
        )
        return QuickBatchRequest(kind=kind, value=value)

    if kind == "040-cleanup":
        agency = st.text_input(
            "Cataloging agency for 040 $d",
            value=st.session_state.get("qb_040_agency", ""),
            key="qb_040_agency",
        )
        return QuickBatchRequest(kind=kind, agency=agency)

    if kind == "856-url":
        action = st.selectbox(
            "856 URL action",
            options=list(_QB_856_ACTION_LABELS),
            format_func=lambda value: _QB_856_ACTION_LABELS.get(value, value),
            key="qb_856_action",
        )
        url_contains = st.text_input(
            "URL contains",
            value=st.session_state.get("qb_856_contains", ""),
            key="qb_856_contains",
        )
        proxy_prefix = ""
        if action in {"add-proxy", "remove-proxy"}:
            proxy_prefix = st.text_input(
                "Proxy prefix",
                value=st.session_state.get("qb_856_proxy_prefix", ""),
                key="qb_856_proxy_prefix",
            )
        return QuickBatchRequest(
            kind=kind,
            action=action,
            url_contains=url_contains,
            proxy_prefix=proxy_prefix,
        )

    if kind == "035-oclc":
        st.caption("Normalizes OCLC-style 035 $a/$z values and leaves 035 $9 alone.")
        return QuickBatchRequest(kind=kind)

    if kind == "9xx-delete":
        tag = st.text_input(
            "Tag to delete",
            value=st.session_state.get("qb_9xx_tag", "9XX"),
            max_chars=3,
            key="qb_9xx_tag",
        )
        return QuickBatchRequest(kind=kind, tag=tag)

    if kind == "sort-fields":
        st.caption("Sorts every MARC field by its three-digit numeric tag and preserves duplicate order.")
        return QuickBatchRequest(kind=kind)

    genre_term = st.text_input(
        "655 $a term",
        value=st.session_state.get("qb_655_term", "Electronic books."),
        key="qb_655_term",
    )
    genre_source = st.text_input(
        "655 $2 source",
        value=st.session_state.get("qb_655_source", "lcgft"),
        key="qb_655_source",
    )
    unwanted_text = st.text_input(
        "Remove existing 655 fields containing",
        value=st.session_state.get("qb_655_unwanted", ""),
        key="qb_655_unwanted",
    )
    return QuickBatchRequest(
        kind=kind,
        genre_term=genre_term,
        genre_source=genre_source,
        unwanted_text=unwanted_text,
    )


def _build_and_store_quick_batch_preview(request: QuickBatchRequest) -> None:
    err = quick_batch.validate_request(request)
    if err:
        st.error(err)
        return

    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload a `.mrc` on Home first.")
        return

    on_progress, progress, status = _quick_batch_progress("Previewing")

    with st.spinner("Building preview…"):
        with _batch_operation(
            "quick-batch", phase="preview", store=store
        ) as measurement:
            preview = quick_batch.build_preview(
                store, request, progress=on_progress
            )
            if _uses_job_file_versions():
                preview.job_file_id = st.session_state.get("job_file_id")
                preview.job_file_version_id = st.session_state.get(
                    "job_file_version_id"
                )
            if preview.error:
                measurement.mark_error("PreviewError")
    progress.empty()
    status.empty()
    batch_replace.cleanup_preview(st.session_state.pop(_K_BR_PREVIEW, None))
    quick_batch.cleanup_preview(st.session_state.get(_K_QB_PREVIEW))
    st.session_state[_K_QB_PREVIEW] = preview


def _render_quick_batch_preview(preview) -> None:
    st.divider()
    if preview.error:
        st.error(preview.error)
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Records", preview.record_count)
    c2.metric("Changed", preview.changed_count)
    c3.metric("Unchanged", preview.skipped_count)

    if getattr(preview.request, "kind", "") == "sort-fields":
        st.caption(
            f"Canonical ordering corrects {preview.inversion_count} tag inversion(s) "
            "while preserving repeated-field order."
        )
        if preview.representative_before:
            st.code(
                "Before tags: " + " ".join(preview.representative_before)
                + "\nAfter tags:  "
                + " ".join(preview.representative_after),
                language="text",
            )

    if preview.changed_count == 0:
        st.info("This operation would not change the loaded batch.")
        return

    if preview.detail_counts:
        rows = [
            {"Detail": detail, "Count": count}
            for detail, count in sorted(preview.detail_counts.items())
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    apply_col, _, _ = st.columns([1, 1, 4])
    if apply_col.button(
        "Apply to batch",
        type="primary",
        key="qb_apply_btn",
    ):
        _apply_quick_batch_preview(preview)


def _apply_quick_batch_preview(preview) -> None:
    store = session.current_store()
    if store is None:
        st.error("No loaded batch — upload one on Home first.")
        return
    record_count = preview.record_count
    on_progress, progress, status = _quick_batch_progress("Checking")
    export_filename = _export_filename(session.current_filename(), "quickbatch")
    if _uses_job_file_versions():
        try:
            version = _adopt_quick_batch_preview(store, preview)
        except (job_files.JobFileError, collaboration.CollaborationError) as exc:
            progress.empty()
            status.empty()
            st.error(str(exc))
            return
        result = quick_batch.QuickBatchResult(
            changed_count=preview.changed_count,
            skipped_count=preview.skipped_count,
        )
        snapshot = None
        quick_batch.cleanup_preview(preview)
        export_source = session.current_store().path
    else:
        version = None
        with snapshot_actions.staged_store_path(store) as before_path:
            with st.spinner(
                f"Applying quick batch operation to {record_count:,} record"
                f"{'s' if record_count != 1 else ''}…"
            ):
                with _batch_operation(
                    "quick-batch", phase="apply", store=store
                ) as measurement:
                    result = quick_batch.apply_preview(
                        store, preview, progress=on_progress
                    )
                    if result.error:
                        measurement.mark_error("ApplyError")
            if result.error:
                progress.empty()
                status.empty()
                st.error(result.error)
                return
            # Non-job Quick Load compatibility boundary: legacy history only.
            snapshot = snapshot_actions.record_job_snapshot(
                job_id=st.session_state.get("current_job_id"),
                user_email=session.current_user_id(),
                kind="quick-batch",
                label=_QB_OPERATION_LABELS.get(
                    preview.request.kind, preview.request.kind
                ),
                before_path=before_path,
                after_path=store.path,
                summary={
                    "operation_kind": preview.request.kind,
                    "changed_count": result.changed_count,
                    "skipped_count": result.skipped_count,
                    "export_filename": export_filename,
                },
            )
        export_source = store.path
    progress.empty()
    status.empty()
    if snapshot is not None:
        audit_event(
            "job-snapshot-created",
            user=session.current_user_id(),
            snapshot_id=snapshot["id"],
            job_id=snapshot["job_id"],
            snapshot_kind=snapshot["kind"],
        )

    audit_event(
        "quick-batch-applied",
        user=session.current_user_id(),
        filename=session.current_filename(),
        operation_kind=preview.request.kind,
        changed_count=result.changed_count,
        skipped_count=result.skipped_count,
    )
    st.session_state["issues_cache"] = {}
    quick_batch.cleanup_preview(st.session_state.pop(_K_QB_PREVIEW, None))
    st.session_state.pop(K_QB_DOWNLOAD_READY, None)
    _cleanup_disk_backed_export(st.session_state.get(_K_QB_EXPORT))
    st.session_state[_K_QB_EXPORT] = _disk_backed_export(
        filename=export_filename,
        source_path=export_source,
        snapshot=snapshot,
        job_file_version=version,
        prefix="marcedit-web-quickbatch-",
    )
    message = f"Applied quick batch operation to {result.changed_count} record(s)"
    if version is not None:
        message += f" as version {version['version_number']}"
    st.success(message + ".")
    st.rerun()


def _adopt_quick_batch_preview(store, preview):
    if (
        preview.store_id != id(store)
        or preview.store_revision != store.revision
        or preview.job_file_id != st.session_state.get("job_file_id")
        or preview.job_file_version_id
        != st.session_state.get("job_file_version_id")
    ):
        raise job_files.JobFileError("Loaded file changed since preview.")
    if preview.output_path is None or not preview.output_path.is_file():
        raise job_files.JobFileError("Preview output is no longer available.")
    with _owned_candidate(
        preview.output_path,
        prefix="marcedit-web-quick-batch-apply-",
    ) as candidate_path:
        return session.adopt_current_candidate(
            candidate_path=candidate_path,
            source_kind="quick-batch",
            label=_QB_OPERATION_LABELS.get(
                preview.request.kind,
                preview.request.kind,
            ),
            summary={
                "operation_kind": preview.request.kind,
                "changed_count": preview.changed_count,
                "skipped_count": preview.skipped_count,
            },
        )


def _render_quick_batch_export() -> None:
    export = st.session_state.get(_K_QB_EXPORT)
    if not export:
        return
    st.markdown("**Updated batch is loaded in this session.**")
    history_id = export.get("snapshot_id") or export.get("job_file_version_id")
    st.caption(_history_location_caption(history_id))
    path_str = export.get("path")
    if not path_str:
        st.caption("Updated export file is not available in this session.")
        return
    path = Path(path_str)
    if not path.exists():
        st.button(
            "Download updated MARC",
            disabled=True,
            help="The temporary export file is no longer available.",
            key="quick_batch_download_missing",
        )
        return
    if not st.session_state.get(K_QB_DOWNLOAD_READY):
        if st.button(
            "Prepare Download updated MARC",
            key="quick_batch_prepare_download",
            help=(
                "Loads the updated MARC file from disk and offers a "
                "download button. This avoids re-reading large files on "
                "every page refresh."
            ),
        ):
            st.session_state[K_QB_DOWNLOAD_READY] = True
            st.rerun()
        return

    st.download_button(
        label="Download updated MARC",
        data=path.read_bytes(),
        file_name=export["filename"],
        mime="application/marc",
        key="quick_batch_download_updated",
    )


def _quick_batch_progress(verb: str, *, min_step: int = 250):
    progress = st.progress(0.0)
    status = st.empty()
    last_rendered = 0

    def on_progress(processed: int, total: int) -> None:
        nonlocal last_rendered
        if total <= 0:
            return
        if (
            processed != 1
            and processed != total
            and processed % min_step != 0
            and processed - last_rendered < min_step
        ):
            return
        last_rendered = processed
        progress.progress(processed / total)
        status.markdown(f"{verb} record {processed:,} of {total:,}…")

    return on_progress, progress, status


def _history_location_caption(snapshot_id) -> str:
    if snapshot_id:
        return (
            "Rollback and before/after downloads are available on the "
            "History page."
        )
    return (
        "Rollback history is only available for signed-in job files. "
        "Download the updated MARC file below."
    )


def _format_leader_position(position: str) -> str:
    labels = {
        "05": "05 — Record status",
        "06": "06 — Type of record",
        "07": "07 — Bibliographic level",
        "08": "08 — Type of control",
        "17": "17 — Encoding level",
        "18": "18 — Descriptive cataloging form",
        "19": "19 — Multipart resource record level",
    }
    return labels.get(position, position)


def _format_code_option(value: str, options) -> str:
    labels = {option.value: option.label for option in options}
    display = "blank" if value == " " else repr(value)
    return f"{display} — {labels.get(value, value)}"
