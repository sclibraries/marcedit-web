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


def list_jobs(user_email: str) -> list[dict[str, Any]]:
    """List active jobs ``user_email`` can access in creation order."""
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT jobs.*, job_access.role AS access_role"
            " FROM jobs"
            " JOIN job_access ON job_access.job_id = jobs.id"
            " WHERE job_access.user_email = ? AND jobs.active = 1"
            " ORDER BY jobs.id",
            (user_email,),
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


def grant_access(
    job_id: int,
    user_email: str,
    role: str,
    *,
    by: str,
) -> dict[str, Any]:
    """Grant ``role`` on ``job_id``. Only the owner can grant access."""
    clean_email = user_email.strip().lower()
    if not clean_email:
        raise JobError("user email is required")
    if role not in {"editor", "viewer"}:
        raise JobError("role must be 'editor' or 'viewer'")

    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_owner(conn, job_id, by)
        existing = _access_row(conn, job_id, clean_email)
        if existing is not None and existing["role"] == "owner":
            raise JobError("owner access cannot be changed")
        conn.execute(
            "INSERT INTO job_access(job_id, user_email, role, created_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(job_id, user_email) DO UPDATE SET role=excluded.role",
            (job_id, clean_email, role, now),
        )
        row = _access_row(conn, job_id, clean_email)
    return _dict(row)


def revoke_access(job_id: int, user_email: str, *, by: str) -> bool:
    """Remove non-owner access from ``job_id``. Only the owner can revoke."""
    clean_email = user_email.strip().lower()
    if not clean_email:
        raise JobError("user email is required")

    db.init_schema()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_owner(conn, job_id, by)
        cur = conn.execute(
            "DELETE FROM job_access"
            " WHERE job_id = ? AND user_email = ? AND role != 'owner'",
            (job_id, clean_email),
        )
    return cur.rowcount == 1


def list_access(job_id: int) -> list[dict[str, Any]]:
    """List all access rows for ``job_id`` in role/display order."""
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT job_id, user_email, role, created_at"
            " FROM job_access"
            " WHERE job_id = ?"
            " ORDER BY CASE role"
            " WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,"
            " user_email",
            (job_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def get_access_role(job_id: int, user_email: str) -> str | None:
    db.init_schema()
    with db.connect() as conn:
        row = _access_row(conn, job_id, user_email)
    return row["role"] if row else None


def require_role(job_id: int, user_email: str, allowed: set[str]) -> str:
    """Return the user's role or raise if it is not in ``allowed``."""
    role = get_access_role(job_id, user_email)
    if role not in allowed:
        raise JobError("job access denied")
    return role


def _job_row(conn, job_id: int):
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def _access_row(conn, job_id: int, user_email: str):
    return conn.execute(
        "SELECT job_id, user_email, role, created_at"
        " FROM job_access WHERE job_id = ? AND user_email = ?",
        (job_id, user_email.strip().lower()),
    ).fetchone()


def _require_owner(conn, job_id: int, user_email: str) -> None:
    row = _access_row(conn, job_id, user_email)
    if row is None or row["role"] != "owner":
        raise JobError("only the job owner can manage access")


def _dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
