"""Atomic immutable saved-task submissions for the durable queue."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Sequence

from . import db, job_files, jobs, operations, sandbox
from .record_store import RecordStore


def _request_payload(
    task_specs: Sequence[sandbox.TaskSpec],
    *,
    submission_token: str,
) -> dict[str, Any]:
    if not task_specs:
        raise operations.OperationError("select at least one task")
    return {
        "version": 1,
        "submission_token": submission_token,
        "tasks": [
            {
                "name": spec.name,
                "body": spec.body,
                "imports": list(spec.imports),
            }
            for spec in task_specs
        ],
    }


def submit_job_task_run(
    *,
    user_email: str,
    file_id: int,
    source_version_id: int,
    task_specs: Sequence[sandbox.TaskSpec],
) -> dict[str, Any]:
    email = user_email.strip().lower()
    submission_token = uuid.uuid4().hex
    request_json = json.dumps(
        _request_payload(task_specs, submission_token=submission_token)
    )
    file_row = job_files.get_file(file_id, email)
    jobs.require_role(
        int(file_row["job_id"]),
        email,
        {"owner", "editor"},
    )
    version = job_files.get_version(source_version_id, email)
    if int(version["job_file_id"]) != file_id:
        raise operations.OperationError("source version does not belong to job file")

    now, expires_at = _retention_times()
    db.init_schema()
    operation_id: int | None = None
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_job_submission_source(
                conn,
                user_email=email,
                file_id=file_id,
                source_version_id=source_version_id,
            )
            operation_id = _insert_operation(
                conn,
                submitted_by=email,
                request_json=request_json,
                total_records=int(version["record_count"]),
                submitted_at=now,
                artifacts_expire_at=expires_at,
                job_id=int(file_row["job_id"]),
                job_file_id=file_id,
                source_version_id=source_version_id,
            )
            _insert_input_artifact(
                conn,
                operation_id=operation_id,
                filename=str(file_row["display_name"]),
                file_path=Path(version["file_path"]),
                record_count=int(version["record_count"]),
                file_bytes=int(version["file_bytes"]),
                queue_owned=False,
                source_version_id=source_version_id,
                created_at=now,
                expires_at=None,
            )
            _record_submitted(conn, operation_id, email, now)
            created = _created_operation(conn, operation_id)
        return created
    except Exception as failure:
        if operation_id is None:
            raise
        try:
            committed = _committed_job_submission(
                operation_id=operation_id,
                submitted_by=email,
                request_json=request_json,
                file_row=file_row,
                version=version,
            )
        except Exception:
            raise failure
        if committed is not None:
            return committed
        raise


def submit_quick_load_task_run(
    *,
    user_email: str,
    source_path: Path,
    filename: str,
    record_count: int,
    task_specs: Sequence[sandbox.TaskSpec],
) -> dict[str, Any]:
    email = user_email.strip().lower()
    submission_token = uuid.uuid4().hex
    request_json = json.dumps(
        _request_payload(task_specs, submission_token=submission_token)
    )
    clean_filename = filename.strip()
    if not clean_filename or not source_path.is_file():
        raise operations.OperationError(
            "a readable MARC file and filename are required"
        )

    pending = operations.operations_root() / "pending"
    copying = pending / f"copying-{submission_token}.mrc"
    candidate = pending / f"ready-{submission_token}.mrc"
    target: Path | None = None
    operation_dir: Path | None = None
    operation_id: int | None = None
    source_size = 0
    copied_size = 0
    try:
        source_size = source_path.stat().st_size
        pending.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source_path, copying)
        except OSError as exc:
            raise operations.OperationError(
                "a readable MARC file and filename are required"
            ) from exc
        operations._fsync_file_and_parent(copying)  # noqa: SLF001
        copied_size = copying.stat().st_size
        if copied_size != source_size:
            raise operations.OperationError(
                "file size does not match the submitted MARC file"
            )
        if RecordStore.from_path(copying).count() != record_count:
            raise operations.OperationError(
                "record count does not match the submitted MARC file"
            )
        os.replace(copying, candidate)
        operations._fsync_directory(pending)  # noqa: SLF001
    except Exception:
        copying.unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)
        raise

    now, expires_at = _retention_times()
    db.init_schema()
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation_id = _insert_operation(
                conn,
                submitted_by=email,
                request_json=request_json,
                total_records=record_count,
                submitted_at=now,
                artifacts_expire_at=expires_at,
            )
            operation_dir = operations.operations_root() / str(operation_id)
            target = operation_dir / f"input-{submission_token}.mrc"
            try:
                operation_dir.mkdir()
            except FileExistsError:
                operations._quarantine_operation_directory(  # noqa: SLF001
                    operation_id
                )
                operation_dir.mkdir()
            os.replace(candidate, target)
            operations._fsync_file_and_parent(target)  # noqa: SLF001
            _insert_input_artifact(
                conn,
                operation_id=operation_id,
                filename=clean_filename,
                file_path=target,
                record_count=record_count,
                file_bytes=copied_size,
                queue_owned=True,
                source_version_id=None,
                created_at=now,
                expires_at=expires_at,
            )
            _record_submitted(conn, operation_id, email, now)
            created = _created_operation(conn, operation_id)
        return created
    except Exception as failure:
        if operation_id is None or target is None:
            # No exact durable identity exists with which to prove rollback.
            # Retain the ready stage for age-protected reconciliation.
            raise
        try:
            committed = _committed_quick_load_submission(
                operation_id=operation_id,
                submitted_by=email,
                request_json=request_json,
                target=target,
                filename=clean_filename,
                record_count=record_count,
                file_bytes=copied_size,
            )
        except Exception:
            # The commit state is unknowable. Retain every byte so a later
            # reconciliation pass can resolve it against durable DB state.
            raise failure
        if committed is not None:
            return committed
        candidate.unlink(missing_ok=True)
        copying.unlink(missing_ok=True)
        _cleanup_quick_load_rollback(target)
        raise


def _committed_quick_load_submission(
    *,
    operation_id: int,
    submitted_by: str,
    request_json: str,
    target: Path,
    filename: str,
    record_count: int,
    file_bytes: int,
) -> dict[str, Any] | None:
    """Resolve a lost commit acknowledgement using a fresh connection."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM operations WHERE id=? AND kind='saved-task-run'"
            " AND submitted_by=? AND request_json=? AND total_records=?"
            " AND job_id IS NULL AND job_file_id IS NULL"
            " AND source_version_id IS NULL",
            (operation_id, submitted_by, request_json, record_count),
        ).fetchone()
        artifact = conn.execute(
            "SELECT 1 FROM operation_artifacts WHERE operation_id=?"
            " AND role='input' AND filename=? AND file_path=? AND record_count=?"
            " AND file_bytes=? AND queue_owned=1",
            (operation_id, filename, str(target), record_count, file_bytes),
        ).fetchone()
    if row is None or artifact is None:
        return None
    return {key: row[key] for key in row.keys()}


def _committed_job_submission(
    *,
    operation_id: int,
    submitted_by: str,
    request_json: str,
    file_row: dict[str, Any],
    version: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve a Job submission's lost commit acknowledgement exactly."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM operations WHERE id=? AND kind='saved-task-run'"
            " AND submitted_by=? AND request_json=? AND total_records=?"
            " AND job_id=? AND job_file_id=? AND source_version_id=?",
            (
                operation_id,
                submitted_by,
                request_json,
                int(version["record_count"]),
                int(file_row["job_id"]),
                int(file_row["id"]),
                int(version["id"]),
            ),
        ).fetchone()
        artifact = conn.execute(
            "SELECT 1 FROM operation_artifacts WHERE operation_id=?"
            " AND role='input' AND filename=? AND file_path=?"
            " AND record_count=? AND file_bytes=? AND queue_owned=0"
            " AND source_version_id=?",
            (
                operation_id,
                str(file_row["display_name"]),
                str(version["file_path"]),
                int(version["record_count"]),
                int(version["file_bytes"]),
                int(version["id"]),
            ),
        ).fetchone()
    if row is None or artifact is None:
        return None
    return {key: row[key] for key in row.keys()}


def _cleanup_quick_load_rollback(target: Path) -> None:
    """Delete only this submission token's confirmed-rollback publication."""
    target.unlink(missing_ok=True)
    try:
        target.parent.rmdir()
    except OSError:
        pass


def _require_job_submission_source(
    conn,
    *,
    user_email: str,
    file_id: int,
    source_version_id: int,
) -> None:
    source = conn.execute(
        "SELECT job_files.job_id FROM job_files"
        " JOIN job_file_versions"
        " ON job_file_versions.job_file_id=job_files.id"
        " WHERE job_files.id=? AND job_file_versions.id=?",
        (file_id, source_version_id),
    ).fetchone()
    if source is None:
        raise operations.OperationError("source version does not belong to job file")
    access = conn.execute(
        "SELECT role FROM job_access"
        " WHERE job_id=? AND user_email=? AND role IN ('owner','editor')",
        (int(source["job_id"]), user_email.strip().lower()),
    ).fetchone()
    if access is None:
        raise jobs.JobError("access denied")


def _created_operation(conn, operation_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM operations WHERE id=?",
        (operation_id,),
    ).fetchone()
    if row is None:
        raise operations.OperationError("operation not found")
    return {key: row[key] for key in row.keys()}


def _insert_operation(
    conn,
    *,
    submitted_by: str,
    request_json: str,
    total_records: int,
    submitted_at: str,
    artifacts_expire_at: str,
    job_id: int | None = None,
    job_file_id: int | None = None,
    source_version_id: int | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO operations(kind, request_version, submitted_by, job_id,"
        " job_file_id, source_version_id, state, phase, request_json,"
        " total_records, submitted_at, artifacts_expire_at)"
        " VALUES ('saved-task-run', 1, ?, ?, ?, ?, 'queued', 'queued', ?, ?, ?, ?)",
        (
            submitted_by,
            job_id,
            job_file_id,
            source_version_id,
            request_json,
            total_records,
            submitted_at,
            artifacts_expire_at,
        ),
    )
    return int(cursor.lastrowid)


def _insert_input_artifact(
    conn,
    *,
    operation_id: int,
    filename: str,
    file_path: Path,
    record_count: int,
    file_bytes: int,
    queue_owned: bool,
    source_version_id: int | None,
    created_at: str,
    expires_at: str | None,
) -> None:
    conn.execute(
        "INSERT INTO operation_artifacts(operation_id, role, filename, file_path,"
        " record_count, file_bytes, queue_owned, source_version_id, created_at,"
        " expires_at) VALUES (?, 'input', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            operation_id,
            filename,
            str(file_path),
            record_count,
            file_bytes,
            int(queue_owned),
            source_version_id,
            created_at,
            expires_at,
        ),
    )


def _record_submitted(conn, operation_id: int, user_email: str, now: str) -> None:
    operations._append_event(  # noqa: SLF001 - queue write-model primitive
        conn,
        operation_id,
        kind="submitted",
        message="Saved task run submitted",
        actor_email=user_email,
        created_at=now,
    )


def _retention_times() -> tuple[str, str]:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    expires_at = now + dt.timedelta(days=operations.retention_days())
    return _iso(now), _iso(expires_at)


def _iso(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
