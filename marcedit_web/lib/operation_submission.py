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
) -> dict[str, Any]:
    if not task_specs:
        raise operations.OperationError("select at least one task")
    return {
        "version": 1,
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
    request_json = json.dumps(_request_payload(task_specs))
    file_row = job_files.get_file(file_id, user_email)
    jobs.require_role(
        int(file_row["job_id"]),
        user_email,
        {"owner", "editor"},
    )
    version = job_files.get_version(source_version_id, user_email)
    if int(version["job_file_id"]) != file_id:
        raise operations.OperationError("source version does not belong to job file")

    now, expires_at = _retention_times()
    db.init_schema()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_job_submission_source(
            conn,
            user_email=user_email,
            file_id=file_id,
            source_version_id=source_version_id,
        )
        operation_id = _insert_operation(
            conn,
            submitted_by=user_email,
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
        _record_submitted(conn, operation_id, user_email, now)
        created = _created_operation(conn, operation_id)
    return created


def submit_quick_load_task_run(
    *,
    user_email: str,
    source_path: Path,
    filename: str,
    record_count: int,
    task_specs: Sequence[sandbox.TaskSpec],
) -> dict[str, Any]:
    request_json = json.dumps(_request_payload(task_specs))
    clean_filename = filename.strip()
    if not clean_filename or not source_path.is_file():
        raise operations.OperationError(
            "a readable MARC file and filename are required"
        )

    candidate = (
        operations.operations_root() / "pending" / f"{uuid.uuid4().hex}.mrc"
    )
    target: Path | None = None
    operation_dir: Path | None = None
    operation_dir_owned = False
    target_owned = False
    try:
        source_size = source_path.stat().st_size
        candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source_path, candidate)
        except OSError as exc:
            raise operations.OperationError(
                "a readable MARC file and filename are required"
            ) from exc
        copied_size = candidate.stat().st_size
        if copied_size != source_size:
            raise operations.OperationError(
                "file size does not match the submitted MARC file"
            )
        if RecordStore.from_path(candidate).count() != record_count:
            raise operations.OperationError(
                "record count does not match the submitted MARC file"
            )

        now, expires_at = _retention_times()
        db.init_schema()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            operation_id = _insert_operation(
                conn,
                submitted_by=user_email,
                request_json=request_json,
                total_records=record_count,
                submitted_at=now,
                artifacts_expire_at=expires_at,
            )
            operation_dir = operations.operations_root() / str(operation_id)
            try:
                operation_dir.mkdir()
            except FileExistsError as exc:
                raise operations.OperationError(
                    "operation artifact directory already exists"
                ) from exc
            operation_dir_owned = True
            target = operation_dir / "input.mrc"
            os.replace(candidate, target)
            target_owned = True
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
            _record_submitted(conn, operation_id, user_email, now)
            created = _created_operation(conn, operation_id)
        return created
    except Exception:
        candidate.unlink(missing_ok=True)
        if target_owned and target is not None:
            target.unlink(missing_ok=True)
        if operation_dir_owned and operation_dir is not None:
            try:
                operation_dir.rmdir()
            except OSError:
                pass
        raise


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
