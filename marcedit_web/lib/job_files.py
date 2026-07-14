"""Durable per-file work items and immutable MARC versions (TASK-151)."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from . import db, jobs


class JobFileError(ValueError):
    """Raised when a job-file operation is invalid."""


def versions_root() -> Path:
    return Path(os.environ.get("MARCEDIT_WEB_JOB_FILES_ROOT", "data/job-files"))


def attach_file(
    *,
    job_id: int,
    user_email: str,
    source_path: Path,
    filename: str,
    record_count: int,
    file_bytes: int,
    upload_id: int | None = None,
    description: str = "",
) -> dict[str, Any]:
    jobs.require_role(job_id, user_email, {"owner", "editor"})
    clean_filename = filename.strip()
    if not clean_filename or not source_path.is_file():
        raise JobFileError("a readable MARC file and filename are required")
    if file_bytes != source_path.stat().st_size:
        raise JobFileError("file size does not match the persisted MARC file")

    now = _utc_now_iso()
    candidate = versions_root() / "pending" / f"{uuid.uuid4().hex}.mrc"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, candidate)
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "INSERT INTO job_files(job_id,original_upload_id,display_name,description,"
                "created_by,created_at,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    upload_id,
                    clean_filename,
                    description.strip(),
                    user_email,
                    now,
                    user_email,
                    now,
                ),
            )
            file_id = int(cursor.lastrowid)
            target = versions_root() / str(file_id) / "versions" / "v000001.mrc"
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(candidate, target)
            version = conn.execute(
                "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
                "record_count,file_bytes,source_kind,label,created_by,created_at) "
                "VALUES(?,1,?,?,?,?,?,?,?) RETURNING id",
                (
                    file_id,
                    str(target),
                    record_count,
                    file_bytes,
                    "original",
                    clean_filename,
                    user_email,
                    now,
                ),
            ).fetchone()
            conn.execute(
                "UPDATE job_files SET current_version_id=? WHERE id=?",
                (version["id"], file_id),
            )
    except Exception:
        candidate.unlink(missing_ok=True)
        if "target" in locals():
            target.unlink(missing_ok=True)
        raise
    return get_file(file_id, user_email)


def list_files(
    job_id: int,
    user_email: str,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    db.init_schema()
    archived_clause = "" if include_archived else " AND job_files.archived_at IS NULL"
    with db.connect() as conn:
        rows = conn.execute(
            _FILE_SELECT
            + " WHERE job_files.job_id=? AND job_access.user_email=?"
            + archived_clause
            + " ORDER BY job_files.id",
            (job_id, user_email.strip().lower()),
        ).fetchall()
    return [_dict(row) for row in rows]


def get_file(file_id: int, user_email: str) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            _FILE_SELECT + " WHERE job_files.id=? AND job_access.user_email=?",
            (file_id, user_email.strip().lower()),
        ).fetchone()
    if row is None:
        raise JobFileError("job file not found")
    return _dict(row)


def get_current_version(file_id: int, user_email: str) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            _VERSION_SELECT
            + " WHERE job_files.id=? AND job_file_versions.id=job_files.current_version_id"
            + " AND job_access.user_email=?",
            (file_id, user_email.strip().lower()),
        ).fetchone()
    if row is None:
        raise JobFileError("job file version not found")
    return _dict(row)


def get_version(version_id: int, user_email: str) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            _VERSION_SELECT
            + " WHERE job_file_versions.id=? AND job_access.user_email=?",
            (version_id, user_email.strip().lower()),
        ).fetchone()
    if row is None:
        raise JobFileError("job file version not found")
    return _dict(row)


_FILE_SELECT = (
    "SELECT job_files.*, job_access.role AS access_role,"
    " job_file_versions.version_number AS current_version_number,"
    " job_file_versions.record_count AS current_record_count,"
    " job_file_versions.file_bytes AS current_file_bytes,"
    " job_file_versions.created_by AS current_version_created_by,"
    " job_file_versions.created_at AS current_version_created_at"
    " FROM job_files"
    " JOIN job_access ON job_access.job_id=job_files.job_id"
    " JOIN job_file_versions ON job_file_versions.id=job_files.current_version_id"
)

_VERSION_SELECT = (
    "SELECT job_file_versions.*, job_files.job_id, job_files.display_name,"
    " job_access.role AS access_role"
    " FROM job_file_versions"
    " JOIN job_files ON job_files.id=job_file_versions.job_file_id"
    " JOIN job_access ON job_access.job_id=job_files.job_id"
)


def _dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
