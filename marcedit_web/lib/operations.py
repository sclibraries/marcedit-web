"""Durable operation queue read model (TASK-156)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from marcedit_web import __version__

from . import db, sandbox


logger = logging.getLogger("marcedit_web.operations")

_VISIBLE_OPERATION_FIELDS = (
    "id", "kind", "submitted_by", "job_id", "job_file_id",
    "source_version_id", "state", "phase", "processed_records",
    "total_records", "output_records", "changed_records", "error_count",
    "terminal_message", "submitted_at", "started_at", "completed_at",
    "artifacts_expire_at", "applied_version_id", "rolled_back_version_id",
)
_ADMIN_DIAGNOSTIC_FIELDS = (
    "attempt", "lease_owner", "lease_heartbeat_at", "lease_expires_at",
    "cancel_requested_by", "cancel_requested_at",
)
_PENDING_READY_GRACE_SECONDS = 15 * 60
_PENDING_COPYING_GRACE_SECONDS = 24 * 60 * 60
_QUARANTINE_DIRECTORY = ".quarantine"


class OperationError(ValueError):
    """Raised when an operation action is missing or unauthorized."""


@dataclass(frozen=True)
class Lease:
    operation_id: int
    token: str
    attempt: int
    request: dict[str, Any]
    input_artifact: dict[str, Any]


def retention_days() -> int:
    raw = os.environ.get("MARCEDIT_WEB_OPERATION_RETENTION_DAYS", "30")
    try:
        days = int(raw)
    except ValueError as exc:
        raise OperationError(
            "MARCEDIT_WEB_OPERATION_RETENTION_DAYS must be a positive integer"
        ) from exc
    if days <= 0:
        raise OperationError(
            "MARCEDIT_WEB_OPERATION_RETENTION_DAYS must be a positive integer"
        )
    return days


def result_download_limit_bytes() -> int:
    raw = os.environ.get(
        "MARCEDIT_WEB_OPERATION_DOWNLOAD_MAX_BYTES",
        str(200 * 1024 * 1024),
    )
    try:
        limit = int(raw)
    except ValueError as exc:
        raise OperationError(
            "MARCEDIT_WEB_OPERATION_DOWNLOAD_MAX_BYTES must be a positive integer"
        ) from exc
    if limit <= 0:
        raise OperationError(
            "MARCEDIT_WEB_OPERATION_DOWNLOAD_MAX_BYTES must be a positive integer"
        )
    return limit


def operations_root() -> Path:
    return Path(
        os.environ.get("MARCEDIT_WEB_OPERATIONS_ROOT", "data/operations")
    )


def get_operation(operation_id: int) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id,)
        ).fetchone()
    if row is None:
        raise OperationError("operation not found")
    return _dict(row)


def list_visible_operations(user_email: str) -> list[dict[str, Any]]:
    """Return a safe page read model for operations visible to the user."""
    db.init_schema()
    email = user_email.strip().lower()
    with db.connect() as conn:
        is_admin = _is_admin(conn, email)
        select = (
            "SELECT operations.id,operations.kind,operations.submitted_by,"
            " operations.job_id,operations.job_file_id,"
            " operations.source_version_id,operations.state,operations.phase,"
            " operations.processed_records,operations.total_records,"
            " operations.output_records,operations.changed_records,"
            " operations.error_count,operations.terminal_message,"
            " operations.submitted_at,operations.started_at,"
            " operations.completed_at,operations.artifacts_expire_at,"
            " operations.applied_version_id,operations.rolled_back_version_id,"
            " operations.request_json AS internal_request_json,"
            " operations.summary_json AS internal_summary_json,"
            " operations.attempt,operations.lease_owner,"
            " operations.lease_heartbeat_at,operations.lease_expires_at,"
            " operations.cancel_requested_by,operations.cancel_requested_at,"
            " jobs.name AS source_job_name,"
            " job_files.display_name AS source_file_name,"
            " job_files.current_version_id AS source_current_version_id,"
            " job_file_versions.version_number AS source_version_number,"
            " job_access.role AS viewer_role,"
            " (SELECT filename FROM operation_artifacts"
            " WHERE operation_id=operations.id AND role='input'"
            " ORDER BY id LIMIT 1) AS source_input_name"
            " FROM operations LEFT JOIN jobs ON jobs.id=operations.job_id"
            " LEFT JOIN job_files ON job_files.id=operations.job_file_id"
            " LEFT JOIN job_file_versions"
            " ON job_file_versions.id=operations.source_version_id"
            " LEFT JOIN job_access ON job_access.job_id=operations.job_id"
            " AND job_access.user_email=?"
        )
        if is_admin:
            rows = conn.execute(
                select
                + " ORDER BY operations.submitted_at DESC, operations.id DESC",
                (email,),
            ).fetchall()
        else:
            rows = conn.execute(
                select
                + " WHERE (operations.job_id IS NULL"
                " AND LOWER(TRIM(operations.submitted_by))=?)"
                " OR (operations.job_id IS NOT NULL"
                " AND job_access.user_email IS NOT NULL)"
                " ORDER BY operations.submitted_at DESC, operations.id DESC",
                (email, email),
            ).fetchall()
    visible: list[dict[str, Any]] = []
    for row in rows:
        raw = _dict(row)
        is_submitter = _same_email(raw["submitted_by"], email)
        has_source_access = (
            is_submitter
            if raw["job_id"] is None
            else raw["viewer_role"] is not None
        )
        can_mutate_job = (
            raw["job_id"] is not None
            and raw["viewer_role"] in {"owner", "editor"}
        )
        item = {key: raw[key] for key in _VISIBLE_OPERATION_FIELDS}
        item["task_names"] = _safe_task_names(raw["internal_request_json"])
        item["summary"] = _safe_operation_summary(raw["internal_summary_json"])
        item["can_access_artifacts"] = has_source_access
        item["can_cancel"] = (
            raw["state"] in {"queued", "running", "cancelling"}
            and (
                is_submitter
                or is_admin
                or raw["viewer_role"] == "owner"
            )
        )
        item["can_apply_result"] = (
            can_mutate_job
            and raw["state"] == "completed"
            and raw["job_file_id"] is not None
            and raw["source_version_id"] is not None
            and raw["source_current_version_id"] == raw["source_version_id"]
            and raw["applied_version_id"] is None
        )
        item["can_rollback_result"] = (
            can_mutate_job
            and raw["state"] == "completed"
            and raw["job_file_id"] is not None
            and raw["source_version_id"] is not None
            and raw["applied_version_id"] is not None
            and raw["source_current_version_id"] == raw["applied_version_id"]
            and raw["rolled_back_version_id"] is None
        )
        if raw["job_id"] is None:
            item["source_label"] = raw["source_input_name"] or "Quick Load file"
        else:
            file_name = raw["source_file_name"] or "Job file"
            version = raw["source_version_number"]
            version_label = f" · v{version}" if version is not None else ""
            job_name = raw["source_job_name"] or "Job"
            item["source_label"] = f"{job_name} · {file_name}{version_label}"
        if is_admin:
            for key in _ADMIN_DIAGNOSTIC_FIELDS:
                item[key] = raw[key]
        visible.append(item)
    return visible


def list_artifacts(
    operation_id: int,
    user_email: str,
) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        _require_visible(conn, operation_id, user_email)
        rows = conn.execute(
            "SELECT * FROM operation_artifacts"
            " WHERE operation_id=? ORDER BY id",
            (operation_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def input_artifact(operation_id: int) -> dict[str, Any]:
    """Return the internal input artifact for a worker or submission service."""
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM operation_artifacts"
            " WHERE operation_id=? AND role='input' ORDER BY id LIMIT 1",
            (operation_id,),
        ).fetchone()
    if row is None:
        raise OperationError("input artifact not found")
    return _dict(row)


def list_events(
    operation_id: int,
    user_email: str,
) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        _require_visible_or_admin(conn, operation_id, user_email)
        rows = conn.execute(
            "SELECT * FROM operation_events"
            " WHERE operation_id=? ORDER BY id",
            (operation_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def list_errors(
    operation_id: int,
    user_email: str,
) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        _require_visible_or_admin(conn, operation_id, user_email)
        rows = conn.execute(
            "SELECT * FROM operation_errors"
            " WHERE operation_id=? ORDER BY ordinal"
            " LIMIT ?",
            (operation_id, sandbox.MAX_RETAINED_ERRORS),
        ).fetchall()
    return [_dict(row) for row in rows]


def claim_next(worker_id: str, *, lease_seconds: int = 30) -> Lease | None:
    if lease_seconds <= 0:
        raise OperationError("lease_seconds must be positive")
    db.init_schema()
    now = _now()
    expires_at = _iso(now + timedelta(seconds=lease_seconds))
    token = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT 1 FROM operations"
            " WHERE state IN ('running','cancelling') LIMIT 1"
        ).fetchone()
        if active is not None:
            return None
        row = conn.execute(
            "SELECT * FROM operations WHERE state='queued'"
            " ORDER BY submitted_at, id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        operation_id = int(row["id"])
        updated = conn.execute(
            "UPDATE operations SET state='running', phase='preparing',"
            " attempt=attempt+1, lease_owner=?, lease_token=?,"
            " lease_heartbeat_at=?, lease_expires_at=?,"
            " started_at=COALESCE(started_at, ?)"
            " WHERE id=? AND state='queued'",
            (
                worker_id,
                token,
                _iso(now),
                expires_at,
                _iso(now),
                operation_id,
            ),
        )
        if updated.rowcount != 1:
            raise OperationError("operation is no longer queued")
        claimed = _operation_row(conn, operation_id)
        artifact = conn.execute(
            "SELECT * FROM operation_artifacts"
            " WHERE operation_id=? AND role='input' ORDER BY id LIMIT 1",
            (operation_id,),
        ).fetchone()
        if claimed is None or artifact is None:
            raise OperationError("input artifact not found")
        _append_event(
            conn,
            operation_id,
            kind="claimed",
            message="Operation claimed for processing",
            actor_email=worker_id,
            created_at=_iso(now),
            details={"attempt": int(claimed["attempt"])},
        )
        return Lease(
            operation_id=operation_id,
            token=token,
            attempt=int(claimed["attempt"]),
            request=json.loads(claimed["request_json"]),
            input_artifact=_dict(artifact),
        )


def renew_lease(
    lease: Lease,
    *,
    lease_seconds: int = 30,
    phase: str | None = None,
    processed_records: int | None = None,
) -> dict[str, Any]:
    if lease_seconds <= 0:
        raise OperationError("lease_seconds must be positive")
    if processed_records is not None and processed_records < 0:
        raise OperationError("processed_records must be nonnegative")
    db.init_schema()
    now = _now()
    assignments = ["lease_heartbeat_at=?", "lease_expires_at=?"]
    values: list[Any] = [
        _iso(now),
        _iso(now + timedelta(seconds=lease_seconds)),
    ]
    if phase is not None:
        assignments.append("phase=?")
        values.append(phase)
    if processed_records is not None:
        assignments.append("processed_records=?")
        values.append(processed_records)
    values.extend((lease.operation_id, lease.token))
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        updated = conn.execute(
            f"UPDATE operations SET {', '.join(assignments)}"
            " WHERE id=? AND state='running' AND lease_token=?",
            values,
        )
        if updated.rowcount != 1:
            raise OperationError("operation is no longer running")
        row = _operation_row(conn, lease.operation_id)
    assert row is not None
    return _dict(row)


def request_cancel(operation_id: int, *, by: str) -> dict[str, Any]:
    db.init_schema()
    email = by.strip().lower()
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _operation_row(conn, operation_id)
        if row is None or not _can_cancel(conn, row, email):
            raise OperationError("operation not found")
        if row["state"] in {"completed", "failed", "cancelled"}:
            raise OperationError("operation is already finished")
        if row["state"] == "cancelling":
            return _dict(row)
        if row["state"] == "queued":
            state = "cancelled"
            phase = "cancelled"
            completed_at = now
            kind = "cancelled"
            message = "Queued operation cancelled"
        else:
            state = "cancelling"
            phase = "cancelling"
            completed_at = None
            kind = "cancel-requested"
            message = "Cancellation requested"
        updated = conn.execute(
            "UPDATE operations SET state=?, phase=?, cancel_requested_by=?,"
            " cancel_requested_at=?, completed_at=? WHERE id=? AND state=?",
            (
                state,
                phase,
                email,
                now,
                completed_at,
                operation_id,
                row["state"],
            ),
        )
        if updated.rowcount != 1:
            raise OperationError("operation state changed")
        _append_event(
            conn,
            operation_id,
            kind=kind,
            message=message,
            actor_email=email,
            created_at=now,
        )
        result = _operation_row(conn, operation_id)
    assert result is not None
    return _dict(result)


def is_cancel_requested(lease: Lease) -> bool:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT state, cancel_requested_at FROM operations"
            " WHERE id=? AND lease_token=?",
            (lease.operation_id, lease.token),
        ).fetchone()
    return row is None or row["state"] != "running" or row["cancel_requested_at"] is not None


def is_lease_cancelling(lease: Lease) -> bool:
    """Return whether the current lease is in a user-requested cancel state.

    Unlike :func:`is_cancel_requested`, this deliberately returns ``False``
    for a stale or missing lease.  The runner uses it to distinguish the
    expected cancellation race from ownership loss after a failed renewal.
    """
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM operations WHERE id=? AND state='cancelling'"
            " AND lease_token=? AND cancel_requested_at IS NOT NULL",
            (lease.operation_id, lease.token),
        ).fetchone()
    return row is not None


def finish_cancelled(lease: Lease) -> dict[str, Any]:
    db.init_schema()
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        updated = conn.execute(
            "UPDATE operations SET state='cancelled', phase='cancelled',"
            " completed_at=?, lease_owner=NULL, lease_token=NULL,"
            " lease_heartbeat_at=NULL, lease_expires_at=NULL"
            " WHERE id=? AND state='cancelling' AND lease_token=?",
            (now, lease.operation_id, lease.token),
        )
        if updated.rowcount != 1:
            raise OperationError("operation is no longer cancelling")
        _append_event(
            conn,
            lease.operation_id,
            kind="cancelled",
            message="Operation cancelled",
            actor_email="__worker__",
            created_at=now,
        )
        row = _operation_row(conn, lease.operation_id)
    assert row is not None
    return _dict(row)


def fail_operation(lease: Lease, *, code: str, message: str) -> dict[str, Any]:
    db.init_schema()
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        updated = conn.execute(
            "UPDATE operations SET state='failed', phase='failed',"
            " terminal_message=?, completed_at=?, lease_owner=NULL,"
            " lease_token=NULL, lease_heartbeat_at=NULL, lease_expires_at=NULL"
            " WHERE id=? AND state='running' AND lease_token=?",
            (message, now, lease.operation_id, lease.token),
        )
        if updated.rowcount != 1:
            raise OperationError("operation is no longer running")
        _append_event(
            conn,
            lease.operation_id,
            kind="failed",
            message=message,
            actor_email="__worker__",
            created_at=now,
            details={"code": code},
        )
        row = _operation_row(conn, lease.operation_id)
    assert row is not None
    return _dict(row)


def complete_operation(
    lease: Lease,
    *,
    result_path: Path,
    output_records: int,
    changed_records: int,
    error_count: int,
    errors: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    if min(output_records, changed_records, error_count) < 0:
        raise OperationError("operation counts must be nonnegative")
    candidate = Path(result_path)
    if not candidate.is_file():
        raise OperationError("result file not found")
    operation_dir = operations_root() / str(lease.operation_id)
    try:
        candidate.resolve().relative_to(operation_dir.resolve())
    except ValueError as exc:
        raise OperationError("result path is not owned by operation") from exc
    published = operation_dir / (
        f"result-attempt-{lease.attempt}-{lease.token}.mrc"
    )
    if candidate == published:
        raise OperationError("operation result already exists")
    db.init_schema()
    now = _iso(_now())
    moved = False
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            owned = conn.execute(
                "SELECT lease_owner FROM operations WHERE id=?"
                " AND state='running' AND lease_token=?"
                " AND cancel_requested_at IS NULL",
                (lease.operation_id, lease.token),
            ).fetchone()
            if owned is None:
                raise OperationError("operation is no longer running")
            if published.exists():
                raise OperationError("operation result already exists")
            os.replace(candidate, published)
            moved = True
            _fsync_file_and_parent(published)
            conn.execute(
                "INSERT INTO operation_artifacts(operation_id, role, filename,"
                " file_path, record_count, file_bytes, queue_owned, created_at)"
                " VALUES (?, 'result', 'result.mrc', ?, ?, ?, 1, ?)",
                (
                    lease.operation_id,
                    str(published),
                    output_records,
                    published.stat().st_size,
                    now,
                ),
            )
            for ordinal, error in enumerate(errors[:sandbox.MAX_RETAINED_ERRORS]):
                bounded_error = sandbox.bound_error(error)
                conn.execute(
                    "INSERT INTO operation_errors(operation_id, ordinal,"
                    " record_index, code, task_name, message)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        lease.operation_id,
                        ordinal,
                        bounded_error["index"],
                        bounded_error["code"],
                        bounded_error["task"],
                        bounded_error["message"],
                    ),
                )
            updated = conn.execute(
                "UPDATE operations SET state='completed', phase='completed',"
                " processed_records=total_records, output_records=?,"
                " changed_records=?, error_count=?, summary_json=?,"
                " completed_at=?, lease_owner=NULL, lease_token=NULL,"
                " lease_heartbeat_at=NULL, lease_expires_at=NULL"
                " WHERE id=? AND state='running' AND lease_token=?"
                " AND cancel_requested_at IS NULL",
                (
                    output_records,
                    changed_records,
                    error_count,
                    json.dumps(summary, sort_keys=True),
                    now,
                    lease.operation_id,
                    lease.token,
                ),
            )
            if updated.rowcount != 1:
                raise OperationError("operation is no longer running")
            _append_event(
                conn,
                lease.operation_id,
                kind="completed",
                message="Operation completed",
                actor_email=str(owned["lease_owner"]),
                created_at=now,
            )
            row = _operation_row(conn, lease.operation_id)
    except Exception as publication_error:
        try:
            committed = _committed_completion(lease.operation_id, published)
        except Exception:
            # Database state is ambiguous. Keep the attempt-specific publication
            # in place so a later reconciliation pass can decide safely.
            raise publication_error
        if committed is not None:
            return committed
        if moved and published.exists() and not candidate.exists():
            try:
                os.replace(published, candidate)
                _fsync_directory(candidate.parent)
            except OSError as exc:
                raise OperationError(
                    "result publication failed and candidate could not be restored"
                ) from exc
        raise publication_error
    assert row is not None
    return _dict(row)


def _committed_completion(
    operation_id: int,
    published: Path,
) -> dict[str, Any] | None:
    """Resolve a lost SQLite commit acknowledgement on a fresh connection."""
    with db.connect() as conn:
        row = _operation_row(conn, operation_id)
        artifact = conn.execute(
            "SELECT 1 FROM operation_artifacts"
            " WHERE operation_id=? AND role='result' AND file_path=? LIMIT 1",
            (operation_id, str(published)),
        ).fetchone()
    if (
        row is not None
        and row["state"] == "completed"
        and artifact is not None
        and published.is_file()
    ):
        return _dict(row)
    return None


def _fsync_file_and_parent(path: Path) -> None:
    with path.open("rb") as published_file:
        os.fsync(published_file.fileno())
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def recover_expired() -> int:
    db.init_schema()
    now = _iso(_now())
    recovered = 0
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id, state, lease_token FROM operations"
            " WHERE state IN ('running','cancelling')"
            " AND lease_expires_at IS NOT NULL AND lease_expires_at < ?"
            " ORDER BY id",
            (now,),
        ).fetchall()
        for row in rows:
            if row["state"] == "running":
                updated = conn.execute(
                    "UPDATE operations SET state='queued', phase='queued',"
                    " processed_records=0, lease_owner=NULL, lease_token=NULL,"
                    " lease_heartbeat_at=NULL, lease_expires_at=NULL"
                    " WHERE id=? AND state='running' AND lease_token=?"
                    " AND lease_expires_at < ?",
                    (row["id"], row["lease_token"], now),
                )
                kind = "recovered"
                message = "Operation restarted after worker interruption"
            else:
                updated = conn.execute(
                    "UPDATE operations SET state='cancelled', phase='cancelled',"
                    " completed_at=?, lease_owner=NULL, lease_token=NULL,"
                    " lease_heartbeat_at=NULL, lease_expires_at=NULL"
                    " WHERE id=? AND state='cancelling' AND lease_token=?"
                    " AND lease_expires_at < ?",
                    (now, row["id"], row["lease_token"], now),
                )
                kind = "cancelled"
                message = "Operation cancelled after worker interruption"
            if updated.rowcount == 1:
                recovered += 1
                _append_event(
                    conn,
                    int(row["id"]),
                    kind=kind,
                    message=message,
                    actor_email="__worker__",
                    created_at=now,
                )
    return recovered


def heartbeat_worker(
    worker_id: str,
    *,
    current_operation_id: int | None,
) -> dict[str, Any]:
    db.init_schema()
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO queue_worker_status(singleton, worker_id, pid,"
            " software_version, started_at, heartbeat_at, current_operation_id)"
            " VALUES (1, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(singleton) DO UPDATE SET worker_id=excluded.worker_id,"
            " pid=excluded.pid, software_version=excluded.software_version,"
            " heartbeat_at=excluded.heartbeat_at,"
            " current_operation_id=excluded.current_operation_id,"
            " started_at=CASE WHEN queue_worker_status.worker_id=excluded.worker_id"
            " THEN queue_worker_status.started_at ELSE excluded.started_at END",
            (worker_id, os.getpid(), __version__, now, now, current_operation_id),
        )
        row = conn.execute(
            "SELECT * FROM queue_worker_status WHERE singleton=1"
        ).fetchone()
    assert row is not None
    return _dict(row)


def worker_health(*, max_age_seconds: int = 15) -> dict[str, Any]:
    if max_age_seconds <= 0:
        raise OperationError("max_age_seconds must be positive")
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM queue_worker_status WHERE singleton=1"
        ).fetchone()
    if row is None:
        return {"available": False, "row": None}
    available = _parse_iso(row["heartbeat_at"]) >= _now() - timedelta(
        seconds=max_age_seconds
    )
    return {"available": available, "row": _dict(row)}


def cleanup_expired_artifacts(now: datetime | None = None) -> int:
    """Delete expired queue-owned bytes while retaining their audit metadata."""
    cleanup_time = _utc(now)
    cleanup_iso = _iso(cleanup_time)
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT operation_artifacts.*,"
            " COALESCE(operation_artifacts.expires_at,"
            " operations.artifacts_expire_at) AS effective_expires_at"
            " FROM operation_artifacts"
            " JOIN operations ON operations.id=operation_artifacts.operation_id"
            " WHERE operation_artifacts.queue_owned=1"
            " AND COALESCE(operation_artifacts.expires_at,"
            " operations.artifacts_expire_at) IS NOT NULL"
            " AND COALESCE(operation_artifacts.expires_at,"
            " operations.artifacts_expire_at) <= ?"
            " AND NOT EXISTS (SELECT 1 FROM job_file_versions"
            " WHERE job_file_versions.file_path=operation_artifacts.file_path)"
            " ORDER BY operation_artifacts.id",
            (cleanup_iso,),
        ).fetchall()

    deleted = 0
    root = operations_root()
    for candidate in rows:
        operation_id = int(candidate["operation_id"])
        artifact_id = int(candidate["id"])
        path = Path(str(candidate["file_path"]))
        removed = False
        recorded = False
        try:
            with db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                eligible = conn.execute(
                    "SELECT 1 FROM operation_artifacts"
                    " JOIN operations"
                    " ON operations.id=operation_artifacts.operation_id"
                    " WHERE operation_artifacts.id=?"
                    " AND operation_artifacts.operation_id=?"
                    " AND operation_artifacts.queue_owned=1"
                    " AND COALESCE(operation_artifacts.expires_at,"
                    " operations.artifacts_expire_at) <= ?"
                    " AND NOT EXISTS (SELECT 1 FROM job_file_versions"
                    " WHERE job_file_versions.file_path="
                    " operation_artifacts.file_path)",
                    (artifact_id, operation_id, cleanup_iso),
                ).fetchone()
                if eligible is None:
                    continue
                details_json = json.dumps(
                    {"artifact_id": artifact_id}, sort_keys=True
                )
                event_exists = conn.execute(
                    "SELECT 1 FROM operation_events WHERE operation_id=?"
                    " AND kind='artifacts-expired' AND details_json=? LIMIT 1",
                    (operation_id, details_json),
                ).fetchone()
                removed = _unlink_queue_artifact(path, root)
                if event_exists is None:
                    _append_event(
                        conn,
                        operation_id,
                        kind="artifacts-expired",
                        message="Operation artifact bytes expired",
                        actor_email="__worker__",
                        created_at=cleanup_iso,
                        details={"artifact_id": artifact_id},
                    )
                    recorded = True
            if removed or recorded:
                deleted += 1
            if removed:
                _remove_empty_attempt_directory(path.parent, root)
        except Exception as exc:
            logger.error(
                "expired artifact cleanup failed operation_id=%s artifact_id=%s",
                operation_id,
                artifact_id,
                exc_info=(
                    RuntimeError,
                    RuntimeError("artifact cleanup error"),
                    exc.__traceback__,
                ),
            )
    return deleted


def cleanup_attempt_workspace(lease: Lease) -> bool:
    """Remove only this lease's private attempt directory without following links."""
    attempt = (
        operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    )
    return _remove_queue_tree(attempt, operations_root())


def reconcile_operation_storage() -> int:
    """Quarantine abandoned paths under a short lock, then delete them."""
    db.init_schema()
    root = operations_root()
    root.mkdir(parents=True, exist_ok=True)
    _ensure_quarantine_directory(root)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        referenced = {
            _absolute_queue_path(Path(row["file_path"]))
            for row in conn.execute(
                "SELECT file_path FROM operation_artifacts"
                " UNION SELECT file_path FROM job_file_versions"
            ).fetchall()
        }
        active_ids = {
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM operations"
                " WHERE state IN ('running','cancelling')"
            ).fetchall()
        }
        operation_ids = {
            int(row["id"])
            for row in conn.execute("SELECT id FROM operations").fetchall()
        }
        _quarantine_storage_paths(referenced, active_ids, operation_ids)
    # Recursive work must never hold SQLite's global writer lock. A crash here
    # is harmless: a later pass retries every entry already in quarantine.
    return _delete_quarantine_entries(root)


def _quarantine_storage_paths(
    referenced: set[Path],
    active_ids: set[int],
    operation_ids: set[int],
) -> None:
    root = operations_root()
    try:
        root_fd = _open_queue_directory(root, ())
    except FileNotFoundError:
        return
    try:
        quarantine_fd = _open_queue_directory(root, (_QUARANTINE_DIRECTORY,))
        try:
            for entry in os.listdir(root_fd):
                if entry == "pending":
                    _quarantine_pending(root_fd, quarantine_fd, root, referenced)
                    continue
                try:
                    operation_id = int(entry)
                except ValueError:
                    continue
                if operation_id not in operation_ids:
                    _quarantine_entry(root_fd, entry, quarantine_fd)
                    continue
                _quarantine_operation_children(
                    root_fd,
                    quarantine_fd,
                    root,
                    entry,
                    active=operation_id in active_ids,
                    referenced=referenced,
                )
        finally:
            os.close(quarantine_fd)
    finally:
        os.close(root_fd)


def list_unread_notifications(user_email: str) -> list[dict[str, Any]]:
    """Return the submitter's source-safe, actionable terminal alerts."""
    db.init_schema()
    email = user_email.strip().lower()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id,state,error_count,completed_at,cancel_requested_by"
            " FROM operations WHERE LOWER(TRIM(submitted_by))=?"
            " AND notification_ack_at IS NULL"
            " AND state IN ('completed','failed','cancelled')"
            " AND (state!='cancelled' OR (cancel_requested_by IS NOT NULL"
            " AND LOWER(TRIM(cancel_requested_by))!="
            " LOWER(TRIM(submitted_by))))"
            " ORDER BY completed_at DESC,id DESC",
            (email,),
        ).fetchall()
    return [_dict(row) for row in rows]


def operation_status_counts(user_email: str) -> dict[str, int]:
    """Return source-visible queue counts without operation metadata."""
    db.init_schema()
    email = user_email.strip().lower()
    with db.connect() as conn:
        if _is_admin(conn, email):
            where = ""
            params: tuple[Any, ...] = ()
        else:
            where = (
                " WHERE (job_id IS NULL AND LOWER(TRIM(submitted_by))=?)"
                " OR (job_id IS NOT NULL AND EXISTS (SELECT 1 FROM job_access"
                " WHERE job_access.job_id=operations.job_id"
                " AND job_access.user_email=?))"
            )
            params = (email, email)
        row = conn.execute(
            "SELECT"
            " COALESCE(SUM(state='queued'),0) AS queued,"
            " COALESCE(SUM(state IN ('running','cancelling')),0) AS running,"
            " COALESCE(SUM(state='failed' OR"
            " (state='completed' AND error_count>0)),0) AS attention"
            " FROM operations" + where,
            params,
        ).fetchone()
    assert row is not None
    return {key: int(row[key]) for key in ("queued", "running", "attention")}


def acknowledge_notification(operation_id: int, *, by: str) -> dict[str, Any]:
    db.init_schema()
    email = by.strip().lower()
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM operations WHERE id=?"
            " AND LOWER(TRIM(submitted_by))=?"
            " AND state IN ('completed','failed','cancelled')"
            " AND (state!='cancelled' OR (cancel_requested_by IS NOT NULL"
            " AND LOWER(TRIM(cancel_requested_by))!="
            " LOWER(TRIM(submitted_by))))",
            (operation_id, email),
        ).fetchone()
        if row is None:
            raise OperationError("operation not found")
        if row["notification_ack_at"] is not None:
            return _dict(row)
        updated = conn.execute(
            "UPDATE operations SET notification_ack_at=?"
            " WHERE id=? AND notification_ack_at IS NULL",
            (now, operation_id),
        )
        if updated.rowcount != 1:
            raise OperationError("operation notification changed")
        _append_event(
            conn,
            operation_id,
            kind="acknowledged",
            message="Operation notification acknowledged",
            actor_email=email,
            created_at=now,
        )
        row = _operation_row(conn, operation_id)
    assert row is not None
    return _dict(row)


def acknowledge_all_notifications(*, by: str) -> int:
    """Acknowledge every currently unread alert owned by ``by`` once."""
    db.init_schema()
    email = by.strip().lower()
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id FROM operations WHERE LOWER(TRIM(submitted_by))=?"
            " AND notification_ack_at IS NULL"
            " AND state IN ('completed','failed','cancelled')"
            " AND (state!='cancelled' OR (cancel_requested_by IS NOT NULL"
            " AND LOWER(TRIM(cancel_requested_by))!="
            " LOWER(TRIM(submitted_by)))) ORDER BY id",
            (email,),
        ).fetchall()
        for row in rows:
            operation_id = int(row["id"])
            conn.execute(
                "UPDATE operations SET notification_ack_at=? WHERE id=?"
                " AND notification_ack_at IS NULL",
                (now, operation_id),
            )
            _append_event(
                conn,
                operation_id,
                kind="acknowledged",
                message="Operation notification acknowledged",
                actor_email=email,
                created_at=now,
            )
    return len(rows)


def _record_result_applied(
    conn: sqlite3.Connection,
    operation_id: int,
    *,
    user_email: str,
    version_id: int,
    job_file_id: int,
    source_version_id: int,
    result_artifact_id: int,
    result_path: Path,
) -> None:
    """Record version publication inside ``adopt_candidate``'s transaction."""
    now = _iso(_now())
    if not result_path.is_file():
        raise OperationError("queued result is no longer available")
    updated = conn.execute(
        "UPDATE operations SET applied_version_id=?,applied_by=?,applied_at=?"
        " WHERE id=? AND state='completed' AND applied_version_id IS NULL"
        " AND job_file_id=? AND source_version_id=?"
        " AND EXISTS (SELECT 1 FROM operation_artifacts"
        " WHERE id=? AND operation_id=operations.id AND role='result'"
        " AND file_path=? AND COALESCE(expires_at,operations.artifacts_expire_at)>?)",
        (
            version_id,
            user_email,
            now,
            operation_id,
            job_file_id,
            source_version_id,
            result_artifact_id,
            str(result_path),
            now,
        ),
    )
    if updated.rowcount != 1:
        raise OperationError("queued result cannot be applied")
    _append_event(
        conn,
        operation_id,
        kind="result-applied",
        message="Queued result applied as a new Job file version",
        actor_email=user_email,
        created_at=now,
        details={"version_id": version_id},
    )


def _record_result_rolled_back(
    conn: sqlite3.Connection,
    operation_id: int,
    *,
    user_email: str,
    applied_version_id: int,
    version_id: int,
    job_file_id: int,
    source_version_id: int,
) -> None:
    """Record rollback publication inside ``adopt_candidate``'s transaction."""
    now = _iso(_now())
    updated = conn.execute(
        "UPDATE operations SET rolled_back_version_id=?,rolled_back_by=?,"
        " rolled_back_at=? WHERE id=? AND state='completed'"
        " AND applied_version_id=? AND job_file_id=? AND source_version_id=?"
        " AND rolled_back_version_id IS NULL",
        (
            version_id,
            user_email,
            now,
            operation_id,
            applied_version_id,
            job_file_id,
            source_version_id,
        ),
    )
    if updated.rowcount != 1:
        raise OperationError("queued result cannot be rolled back")
    _append_event(
        conn,
        operation_id,
        kind="result-rolled-back",
        message="Queued result rolled back as a new Job file version",
        actor_email=user_email,
        created_at=now,
        details={
            "applied_version_id": applied_version_id,
            "version_id": version_id,
        },
    )


def _operation_row(
    conn: sqlite3.Connection,
    operation_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM operations WHERE id=?",
        (operation_id,),
    ).fetchone()


def _is_visible(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    user_email: str,
) -> bool:
    if row["job_id"] is None:
        return _same_email(row["submitted_by"], user_email)
    email = user_email.strip().lower()
    access = conn.execute(
        "SELECT 1 FROM job_access WHERE job_id=? AND user_email=?",
        (row["job_id"], email),
    ).fetchone()
    return access is not None


def _is_admin(
    conn: sqlite3.Connection,
    user_email: str,
) -> bool:
    return conn.execute(
        "SELECT 1 FROM users WHERE email=? AND role='admin' AND status='approved'",
        (user_email.strip().lower(),),
    ).fetchone() is not None


def _can_cancel(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    user_email: str,
) -> bool:
    email = user_email.strip().lower()
    if _same_email(row["submitted_by"], email) or _is_admin(conn, email):
        return True
    if row["job_id"] is None:
        return False
    return conn.execute(
        "SELECT 1 FROM job_access WHERE job_id=? AND user_email=? AND role='owner'",
        (row["job_id"], email),
    ).fetchone() is not None


def _same_email(left: str, right: str) -> bool:
    return left.strip().lower() == right.strip().lower()


def _require_visible(
    conn: sqlite3.Connection,
    operation_id: int,
    user_email: str,
) -> sqlite3.Row:
    row = _operation_row(conn, operation_id)
    if row is None or not _is_visible(conn, row, user_email):
        raise OperationError("operation not found")
    return row


def _require_visible_or_admin(
    conn: sqlite3.Connection,
    operation_id: int,
    user_email: str,
) -> sqlite3.Row:
    row = _operation_row(conn, operation_id)
    if row is None or not (
        _is_visible(conn, row, user_email) or _is_admin(conn, user_email)
    ):
        raise OperationError("operation not found")
    return row


def _append_event(
    conn: sqlite3.Connection,
    operation_id: int,
    *,
    kind: str,
    message: str,
    actor_email: str,
    created_at: str,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO operation_events(operation_id, kind, message,"
        " actor_email, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            operation_id,
            kind,
            message,
            actor_email,
            json.dumps(details or {}, sort_keys=True),
            created_at,
        ),
    )


def _safe_task_names(raw: str) -> list[str]:
    try:
        request = json.loads(raw)
    except (TypeError, ValueError):
        return []
    tasks = request.get("tasks", []) if isinstance(request, dict) else []
    if not isinstance(tasks, list):
        return []
    return [
        str(task.get("name", "")).strip()
        for task in tasks
        if isinstance(task, dict) and str(task.get("name", "")).strip()
    ]


def _safe_operation_summary(raw: str) -> dict[str, int]:
    try:
        summary = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(summary, dict):
        return {}
    keys = {"input_records", "output_records", "changed_records", "error_count"}
    return {
        key: value
        for key, value in summary.items()
        if key in keys and isinstance(value, int) and value >= 0
    }


def _dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return _now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _unlink_queue_artifact(path: Path, root: Path) -> bool:
    relative = _relative_queue_path(path, root)
    try:
        parent_fd = _open_queue_directory(root, relative.parts[:-1])
    except FileNotFoundError:
        return False
    try:
        name = relative.parts[-1]
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if stat.S_ISDIR(metadata.st_mode):
            raise OSError("queue artifact path is a directory")
        os.unlink(name, dir_fd=parent_fd)
        return True
    finally:
        os.close(parent_fd)


def _remove_empty_attempt_directory(path: Path, root: Path) -> None:
    if not path.name.startswith("attempt-"):
        return
    relative = _relative_queue_path(path, root)
    try:
        parent_fd = _open_queue_directory(root, relative.parts[:-1])
    except OSError:
        return
    try:
        os.rmdir(relative.parts[-1], dir_fd=parent_fd)
    except OSError:
        return
    finally:
        os.close(parent_fd)


def _relative_queue_path(path: Path, root: Path) -> Path:
    absolute_root = Path(os.path.abspath(str(root)))
    absolute_path = Path(os.path.abspath(str(path)))
    relative = absolute_path.relative_to(absolute_root)
    if not relative.parts:
        raise ValueError("queue artifact path is the operations root")
    return relative


def _absolute_queue_path(path: Path) -> Path:
    return Path(os.path.abspath(str(path)))


def _remove_queue_tree(path: Path, root: Path) -> bool:
    relative = _relative_queue_path(path, root)
    try:
        parent_fd = _open_queue_directory(root, relative.parts[:-1])
    except FileNotFoundError:
        return False
    try:
        return _remove_tree_entry(parent_fd, relative.parts[-1])
    finally:
        os.close(parent_fd)


def _remove_tree_entry(parent_fd: int, name: str) -> bool:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(metadata.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        return True
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    child_fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        for child in os.listdir(child_fd):
            _remove_tree_entry(child_fd, child)
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=parent_fd)
    return True


def _ensure_quarantine_directory(root: Path) -> None:
    try:
        (root / _QUARANTINE_DIRECTORY).mkdir()
    except FileExistsError:
        pass
    descriptor = _open_queue_directory(root, (_QUARANTINE_DIRECTORY,))
    os.close(descriptor)


def _quarantine_operation_directory(operation_id: int) -> bool:
    """Atomically displace an ID-reuse orphan without recursive deletion."""
    root = operations_root()
    _ensure_quarantine_directory(root)
    root_fd = _open_queue_directory(root, ())
    try:
        quarantine_fd = _open_queue_directory(root, (_QUARANTINE_DIRECTORY,))
        try:
            return _quarantine_entry(root_fd, str(operation_id), quarantine_fd)
        finally:
            os.close(quarantine_fd)
    finally:
        os.close(root_fd)


def _quarantine_entry(parent_fd: int, name: str, quarantine_fd: int) -> bool:
    quarantine_name = f"{uuid.uuid4().hex}-{name}"
    try:
        os.rename(
            name,
            quarantine_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=quarantine_fd,
        )
    except FileNotFoundError:
        return False
    return True


def _delete_quarantine_entries(root: Path) -> int:
    try:
        quarantine_fd = _open_queue_directory(root, (_QUARANTINE_DIRECTORY,))
    except OSError:
        return 0
    removed = 0
    try:
        for name in os.listdir(quarantine_fd):
            try:
                if _remove_tree_entry(quarantine_fd, name):
                    removed += 1
            except OSError:
                continue
    finally:
        os.close(quarantine_fd)
    return removed


def _quarantine_pending(
    root_fd: int,
    quarantine_fd: int,
    root: Path,
    referenced: set[Path],
) -> None:
    try:
        pending_fd = os.open(
            "pending",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
    except OSError:
        return
    try:
        for name in os.listdir(pending_fd):
            path = _absolute_queue_path(root / "pending" / name)
            if path in referenced:
                continue
            grace_seconds = None
            if name.startswith("copying-"):
                # Copy plus MARC validation can be lengthy for the maximum
                # supported input. A full day protects a live submitter while
                # still allowing hard-kill debris to be reclaimed.
                grace_seconds = _PENDING_COPYING_GRACE_SECONDS
            elif name.startswith("ready-"):
                grace_seconds = _PENDING_READY_GRACE_SECONDS
            if grace_seconds is not None:
                try:
                    age = _now().timestamp() - os.stat(
                        name,
                        dir_fd=pending_fd,
                        follow_symlinks=False,
                    ).st_mtime
                except OSError:
                    continue
                if age < grace_seconds:
                    continue
            try:
                _quarantine_entry(pending_fd, name, quarantine_fd)
            except OSError:
                continue
    finally:
        os.close(pending_fd)


def _quarantine_operation_children(
    root_fd: int,
    quarantine_fd: int,
    root: Path,
    entry: str,
    *,
    active: bool,
    referenced: set[Path],
) -> None:
    try:
        operation_fd = os.open(
            entry,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
    except OSError:
        return
    try:
        for name in os.listdir(operation_fd):
            is_attempt = name.startswith("attempt-")
            is_publication = name.startswith("result-attempt-")
            path = _absolute_queue_path(root / entry / name)
            eligible = (
                (is_attempt and not active)
                or (is_publication and path not in referenced)
            )
            if eligible:
                try:
                    _quarantine_entry(operation_fd, name, quarantine_fd)
                except OSError:
                    continue
    finally:
        os.close(operation_fd)


def _open_queue_directory(root: Path, parts: tuple[str, ...]) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise OSError("safe directory-relative cleanup is unavailable")
    flags = os.O_RDONLY | directory | no_follow
    current_fd = os.open(Path(os.path.abspath(str(root))), flags)
    try:
        for part in parts:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise
