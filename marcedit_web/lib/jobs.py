"""Server-side job/project helpers (TASK-081)."""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from . import db

DEFAULT_JOB_NAME = "Personal uploads"


class JobError(ValueError):
    """Raised when a job operation is invalid."""


def ensure_default_job(owner_email: str) -> dict[str, Any]:
    """Return the user's default personal job, creating it if needed."""
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job_id = db._ensure_default_job(conn, owner_email, now)  # noqa: SLF001
        row = _job_row(conn, job_id)
    return _dict(row)


def create_job(
    owner_email: str,
    name: str,
    *,
    description: str = "",
    visibility: str = "private",
) -> dict[str, Any]:
    """Create a named job owned by ``owner_email``."""
    clean_name = name.strip()
    if not clean_name:
        raise JobError("job name is required")
    if visibility not in {"private", "shared"}:
        raise JobError("visibility must be 'private' or 'shared'")

    db.init_schema()
    now = _utc_now_iso()
    try:
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO jobs(owner_email, name, description, visibility,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (owner_email, clean_name, description, visibility, now, now),
            )
            job_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO job_access(job_id, user_email, role, created_at)"
                " VALUES (?, ?, 'owner', ?)",
                (job_id, owner_email, now),
            )
            row = _job_row(conn, job_id)
    except sqlite3.IntegrityError as exc:
        raise JobError(f"job already exists for owner/name: {clean_name}") from exc
    return _dict(row)


def list_jobs(owner_email: str) -> list[dict[str, Any]]:
    """List active jobs owned by ``owner_email`` in creation order."""
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs"
            " WHERE owner_email = ? AND active = 1"
            " ORDER BY id",
            (owner_email,),
        ).fetchall()
    return [_dict(row) for row in rows]


def get_job(job_id: int) -> dict[str, Any] | None:
    db.init_schema()
    with db.connect() as conn:
        row = _job_row(conn, job_id)
    return _dict(row) if row else None


def list_job_uploads(job_id: int) -> list[dict[str, Any]]:
    """List uploads attached to a job, oldest first."""
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM uploads WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def _job_row(conn, job_id: int):
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def _dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
