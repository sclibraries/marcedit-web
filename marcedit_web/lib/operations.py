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
    """Return operations whose current source access includes the user."""
    db.init_schema()
    with db.connect() as conn:
        if _is_admin(conn, user_email):
            rows = conn.execute(
                "SELECT * FROM operations"
                " ORDER BY submitted_at DESC, id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT operations.* FROM operations"
                " LEFT JOIN job_access"
                " ON job_access.job_id=operations.job_id"
                " AND job_access.user_email=?"
                " WHERE (operations.job_id IS NULL"
                " AND operations.submitted_by=?)"
                " OR (operations.job_id IS NOT NULL"
                " AND job_access.user_email IS NOT NULL)"
                " ORDER BY operations.submitted_at DESC, operations.id DESC",
                (user_email, user_email),
            ).fetchall()
    return [_dict(row) for row in rows]


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
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _operation_row(conn, operation_id)
        if row is None or not _can_cancel(conn, row, by):
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
                by,
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
            actor_email=by,
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
    published = operation_dir / "result.mrc"
    if published.exists() or candidate == published:
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
            os.replace(candidate, published)
            moved = True
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
                conn.execute(
                    "INSERT INTO operation_errors(operation_id, ordinal,"
                    " record_index, code, task_name, message)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        lease.operation_id,
                        ordinal,
                        int(error.get("index", 0)),
                        str(error.get("code", "operation-error")),
                        error.get("task"),
                        str(error.get("message", "")),
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
    except Exception:
        if moved:
            try:
                os.replace(published, candidate)
            except OSError as exc:
                raise OperationError(
                    "result publication failed and candidate could not be restored"
                ) from exc
        raise
    assert row is not None
    return _dict(row)


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


def acknowledge_notification(operation_id: int, *, by: str) -> dict[str, Any]:
    db.init_schema()
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        updated = conn.execute(
            "UPDATE operations SET notification_ack_at=?"
            " WHERE id=? AND submitted_by=?"
            " AND state IN ('completed','failed','cancelled')",
            (now, operation_id, by),
        )
        if updated.rowcount != 1:
            raise OperationError("operation not found")
        _append_event(
            conn,
            operation_id,
            kind="acknowledged",
            message="Operation notification acknowledged",
            actor_email=by,
            created_at=now,
        )
        row = _operation_row(conn, operation_id)
    assert row is not None
    return _dict(row)


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
        return row["submitted_by"] == user_email
    access = conn.execute(
        "SELECT 1 FROM job_access WHERE job_id=? AND user_email=?",
        (row["job_id"], user_email),
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
    if row["submitted_by"] == email or _is_admin(conn, email):
        return True
    if row["job_id"] is None:
        return False
    return conn.execute(
        "SELECT 1 FROM job_access WHERE job_id=? AND user_email=? AND role='owner'",
        (row["job_id"], email),
    ).fetchone() is not None


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
