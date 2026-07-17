"""Review actions for retained durable-operation results (TASK-156)."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, job_files, operations, session
from .record_store import RecordStore


def apply_job_result(
    operation_id: int,
    *,
    user_email: str,
    opened_version_id: int,
) -> dict[str, Any]:
    """Publish one completed retained result as an immutable Job version."""
    email = user_email.strip().lower()
    operation, result = _job_result_for_apply(operation_id, email)
    source_version_id = int(operation["source_version_id"])
    if opened_version_id != source_version_id:
        raise operations.OperationError(
            "open the queued operation's exact source version before applying"
        )

    result_path = Path(result["file_path"])
    apply_copy = _private_copy_path(operation_id, "apply")
    try:
        _copy_available(result_path, apply_copy, "queued result")

        def record_apply(conn, created: dict[str, Any]) -> None:
            operations._record_result_applied(  # noqa: SLF001
                conn,
                operation_id,
                user_email=email,
                version_id=int(created["id"]),
                job_file_id=int(operation["job_file_id"]),
                source_version_id=source_version_id,
                result_artifact_id=int(result["id"]),
                result_path=result_path,
            )

        created = job_files.adopt_candidate(
            file_id=int(operation["job_file_id"]),
            opened_version_id=opened_version_id,
            user_email=email,
            candidate_path=apply_copy,
            source_kind="queued-task",
            label=_operation_label(operation),
            summary=_summary(operation),
            validation={"error_count": int(operation["error_count"])},
            transaction_hook=record_apply,
        )
    except operations.OperationError:
        raise
    except job_files.JobFileError as exc:
        current = operations.get_operation(operation_id)
        if current["applied_version_id"] is not None:
            raise operations.OperationError(
                "queued result already applied"
            ) from exc
        raise operations.OperationError(str(exc)) from exc
    finally:
        _remove_private_copy(apply_copy)
    return created


def rollback_job_result(
    operation_id: int,
    *,
    user_email: str,
    opened_version_id: int,
) -> dict[str, Any]:
    """Restore source bytes by publishing another immutable Job version."""
    email = user_email.strip().lower()
    operation = _job_operation_for_rollback(operation_id, email)
    applied_version_id = int(operation["applied_version_id"])
    if opened_version_id != applied_version_id:
        raise operations.OperationError(
            "open the exact applied version before rolling back"
        )
    try:
        source = job_files.get_version(
            int(operation["source_version_id"]), email
        )
    except job_files.JobFileError as exc:
        raise operations.OperationError(
            "source version is no longer available"
        ) from exc
    if int(source["job_file_id"]) != int(operation["job_file_id"]):
        raise operations.OperationError(
            "source version does not belong to this Job file"
        )

    rollback_copy = _private_copy_path(operation_id, "rollback")
    try:
        _copy_available(
            Path(source["file_path"]), rollback_copy, "source version"
        )

        def record_rollback(conn, created: dict[str, Any]) -> None:
            operations._record_result_rolled_back(  # noqa: SLF001
                conn,
                operation_id,
                user_email=email,
                applied_version_id=applied_version_id,
                version_id=int(created["id"]),
                job_file_id=int(operation["job_file_id"]),
                source_version_id=int(operation["source_version_id"]),
            )

        created = job_files.adopt_candidate(
            file_id=int(operation["job_file_id"]),
            opened_version_id=opened_version_id,
            user_email=email,
            candidate_path=rollback_copy,
            source_kind="queued-task-rollback",
            label=f"Rollback of {_operation_label(operation)}",
            summary={"rolled_back_operation_id": operation_id},
            validation={},
            transaction_hook=record_rollback,
        )
    except operations.OperationError:
        raise
    except job_files.JobFileError as exc:
        current = operations.get_operation(operation_id)
        if current["rolled_back_version_id"] is not None:
            raise operations.OperationError(
                "queued result already rolled back"
            ) from exc
        raise operations.OperationError(str(exc)) from exc
    finally:
        _remove_private_copy(rollback_copy)
    return created


def reopen_quick_load(
    operation_id: int,
    *,
    user_email: str,
    use_result: bool,
) -> RecordStore:
    """Reopen retained Quick Load input or result without consuming it."""
    email = user_email.strip().lower()
    if session.current_user_id().strip().lower() != email:
        raise operations.OperationError("operation not found")
    operation, artifact = _quick_artifact(operation_id, email, use_result)
    input_name = str(operation["input_filename"])
    stem = Path(input_name).stem or "queued-operation"
    filename = (
        f"{stem}-queued-result.mrc" if use_result else f"{stem}-original.mrc"
    )
    path = Path(artifact["file_path"])
    if not path.is_file():
        raise operations.OperationError("selected artifact is no longer available")
    try:
        return session.replace_current_store_from_path(
            path,
            filename=filename,
            job_id=None,
            quick_load=True,
        )
    except (OSError, ValueError) as exc:
        raise operations.OperationError(
            "selected artifact could not be reopened"
        ) from exc


def _job_result_for_apply(
    operation_id: int,
    user_email: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    db.init_schema()
    now = _now_iso()
    with db.connect() as conn:
        operation = conn.execute(
            "SELECT operations.*,job_access.role AS action_role"
            " FROM operations LEFT JOIN job_access"
            " ON job_access.job_id=operations.job_id AND job_access.user_email=?"
            " WHERE operations.id=?",
            (user_email, operation_id),
        ).fetchone()
        if operation is None or operation["job_file_id"] is None:
            raise operations.OperationError("Job operation not found")
        if operation["action_role"] not in {"owner", "editor"}:
            raise operations.OperationError("owner or editor access required")
        if operation["state"] != "completed":
            raise operations.OperationError(
                "operation must be completed before applying"
            )
        if operation["applied_version_id"] is not None:
            raise operations.OperationError("queued result already applied")
        artifact = conn.execute(
            "SELECT operation_artifacts.*,"
            " COALESCE(operation_artifacts.expires_at,operations.artifacts_expire_at)"
            " AS effective_expires_at FROM operation_artifacts"
            " JOIN operations ON operations.id=operation_artifacts.operation_id"
            " WHERE operation_artifacts.operation_id=?"
            " AND operation_artifacts.role='result' ORDER BY operation_artifacts.id"
            " DESC LIMIT 1",
            (operation_id,),
        ).fetchone()
    if artifact is None:
        raise operations.OperationError("queued result is no longer available")
    if artifact["effective_expires_at"] is not None and artifact[
        "effective_expires_at"
    ] <= now:
        raise operations.OperationError("queued result has expired")
    return _dict(operation), _dict(artifact)


def _job_operation_for_rollback(
    operation_id: int,
    user_email: str,
) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT operations.*,job_access.role AS action_role"
            " FROM operations LEFT JOIN job_access"
            " ON job_access.job_id=operations.job_id AND job_access.user_email=?"
            " WHERE operations.id=?",
            (user_email, operation_id),
        ).fetchone()
    if row is None or row["job_file_id"] is None:
        raise operations.OperationError("Job operation not found")
    if row["action_role"] not in {"owner", "editor"}:
        raise operations.OperationError("owner or editor access required")
    if row["state"] != "completed" or row["applied_version_id"] is None:
        raise operations.OperationError("queued result has not been applied")
    if row["rolled_back_version_id"] is not None:
        raise operations.OperationError("queued result already rolled back")
    return _dict(row)


def _quick_artifact(
    operation_id: int,
    user_email: str,
    use_result: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    role = "result" if use_result else "input"
    db.init_schema()
    now = _now_iso()
    with db.connect() as conn:
        operation = conn.execute(
            "SELECT operations.*,input.filename AS input_filename"
            " FROM operations JOIN operation_artifacts AS input"
            " ON input.operation_id=operations.id AND input.role='input'"
            " WHERE operations.id=? AND operations.job_id IS NULL"
            " AND operations.submitted_by=?",
            (operation_id, user_email),
        ).fetchone()
        if operation is None:
            raise operations.OperationError("operation not found")
        if operation["state"] != "completed":
            raise operations.OperationError(
                "operation must be completed before reopening"
            )
        artifact = conn.execute(
            "SELECT operation_artifacts.*,"
            " COALESCE(operation_artifacts.expires_at,operations.artifacts_expire_at)"
            " AS effective_expires_at FROM operation_artifacts"
            " JOIN operations ON operations.id=operation_artifacts.operation_id"
            " WHERE operation_artifacts.operation_id=?"
            " AND operation_artifacts.role=? ORDER BY operation_artifacts.id"
            " DESC LIMIT 1",
            (operation_id, role),
        ).fetchone()
    if artifact is None:
        raise operations.OperationError("selected artifact is no longer available")
    if artifact["effective_expires_at"] is not None and artifact[
        "effective_expires_at"
    ] <= now:
        raise operations.OperationError("selected artifact has expired")
    return _dict(operation), _dict(artifact)


def _private_copy_path(operation_id: int, action: str) -> Path:
    directory = operations.operations_root() / str(operation_id) / "actions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{action}-{uuid.uuid4().hex}.mrc"


def _copy_available(source: Path, target: Path, label: str) -> None:
    try:
        shutil.copyfile(source, target)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise operations.OperationError(f"{label} is no longer available") from exc


def _remove_private_copy(path: Path) -> None:
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def _operation_label(operation: dict[str, Any]) -> str:
    try:
        tasks = json.loads(operation["request_json"]).get("tasks", [])
    except (TypeError, ValueError):
        tasks = []
    names = [str(task.get("name", "")).strip() for task in tasks]
    names = [name for name in names if name]
    if not names:
        return "Queued saved-task result"
    return "Queued task: " + ", ".join(names)


def _summary(operation: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(operation["summary_json"])
    except (TypeError, ValueError) as exc:
        raise operations.OperationError("operation summary is invalid") from exc
    if not isinstance(value, dict):
        raise operations.OperationError("operation summary is invalid")
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
