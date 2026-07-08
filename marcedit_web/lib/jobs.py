"""Server-side job/project helpers (TASK-081)."""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from . import db

DEFAULT_JOB_NAME = "Personal uploads"
STATUS_ACTIVE = "active"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_CHANGES_REQUESTED = "changes_requested"
STATUS_APPROVED = "approved"
STATUS_READY_TO_LOAD = "ready_to_load"
STATUS_COMPLETE = "complete"
STATUS_ARCHIVED = "archived"

JOB_STATUSES = (
    STATUS_ACTIVE,
    STATUS_NEEDS_REVIEW,
    STATUS_CHANGES_REQUESTED,
    STATUS_APPROVED,
    STATUS_READY_TO_LOAD,
    STATUS_COMPLETE,
    STATUS_ARCHIVED,
)


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


def list_job_summaries(
    user_email: str,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """List jobs with counts needed by the Jobs page."""
    db.init_schema()
    active_clause = "" if include_archived else " AND jobs.active = 1"
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT jobs.id, jobs.name, jobs.owner_email, jobs.status,"
            " jobs.updated_at, jobs.active, job_access.role AS access_role,"
            " COUNT(DISTINCT uploads.id) AS file_count,"
            " COUNT(DISTINCT CASE WHEN job_review_notes.resolved = 0"
            " THEN job_review_notes.id END) AS open_note_count"
            " FROM jobs"
            " JOIN job_access ON job_access.job_id = jobs.id"
            " LEFT JOIN uploads ON uploads.job_id = jobs.id"
            " LEFT JOIN job_review_notes ON job_review_notes.job_id = jobs.id"
            " WHERE job_access.user_email = ?"
            + active_clause
            + " GROUP BY jobs.id, jobs.name, jobs.owner_email, jobs.status,"
            " jobs.updated_at, jobs.active, job_access.role"
            " ORDER BY jobs.updated_at DESC, jobs.id DESC",
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
    db.init_schema()
    with db.connect() as conn:
        return _require_role(conn, job_id, user_email, allowed)


def set_status(
    job_id: int,
    status: str,
    *,
    by: str,
    note: str = "",
) -> dict[str, Any]:
    """Set advisory workflow status for a job."""
    if status not in JOB_STATUSES:
        raise JobError("invalid job status")
    if status == STATUS_ARCHIVED:
        return archive_job(job_id, by=by)
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_role(conn, job_id, by, {"owner", "editor"})
        row = _job_row(conn, job_id)
        if row is None:
            raise JobError("job not found")
        if row["active"] == 0 or row["status"] == STATUS_ARCHIVED:
            raise JobError("archived jobs must be restored before status changes")
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, job_id),
        )
        message = f"Status changed to {status}"
        if note.strip():
            message = f"{message}: {note.strip()}"
        _record_activity(conn, job_id, "status-changed", message, by, now)
        row = _job_row(conn, job_id)
    return _dict(row)


def archive_job(job_id: int, *, by: str) -> dict[str, Any]:
    """Soft archive a job. Upload and review history remains available."""
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_owner(conn, job_id, by)
        row = _job_row(conn, job_id)
        if row is None:
            raise JobError("job not found")
        if row["name"] == DEFAULT_JOB_NAME:
            raise JobError("Personal uploads cannot be archived")
        conn.execute(
            "UPDATE jobs"
            " SET active = 0, status = ?, archived_at = ?, archived_by = ?,"
            " updated_at = ?"
            " WHERE id = ?",
            (STATUS_ARCHIVED, now, by, now, job_id),
        )
        _record_activity(conn, job_id, "job-archived", "Job archived", by, now)
        row = _job_row(conn, job_id)
    return _dict(row)


def restore_job(job_id: int, *, by: str) -> dict[str, Any]:
    """Restore an archived job to active status."""
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_owner(conn, job_id, by)
        row = _job_row(conn, job_id)
        if row is None:
            raise JobError("job not found")
        conn.execute(
            "UPDATE jobs"
            " SET active = 1, status = ?, archived_at = NULL, archived_by = NULL,"
            " updated_at = ?"
            " WHERE id = ?",
            (STATUS_ACTIVE, now, job_id),
        )
        _record_activity(conn, job_id, "job-restored", "Job restored", by, now)
        row = _job_row(conn, job_id)
    return _dict(row)


def list_activity(job_id: int, *, user_email: str) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        _require_role(conn, job_id, user_email, {"owner", "editor", "viewer"})
        rows = conn.execute(
            "SELECT * FROM job_activity WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def add_review_note(
    job_id: int,
    *,
    anchor_kind: str,
    note: str,
    author: str,
    anchor_value: str = "",
    category: str = "note",
) -> dict[str, Any]:
    clean_note = note.strip()
    clean_anchor = anchor_kind.strip()
    clean_category = category.strip() or "note"
    if not clean_anchor:
        raise JobError("note anchor is required")
    if not clean_note:
        raise JobError("note text is required")
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_role(conn, job_id, author, {"owner", "editor"})
        cur = conn.execute(
            "INSERT INTO job_review_notes"
            "(job_id, anchor_kind, anchor_value, note, author_email, category,"
            " created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                clean_anchor,
                anchor_value.strip(),
                clean_note,
                author,
                clean_category,
                now,
            ),
        )
        note_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        _record_activity(conn, job_id, "note-added", clean_note, author, now)
        row = _review_note_row(conn, note_id)
    return _dict(row)


def resolve_review_note(note_id: int, *, by: str) -> dict[str, Any]:
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _review_note_row(conn, note_id)
        if row is None:
            raise JobError("review note not found")
        job_id = int(row["job_id"])
        _require_role(conn, job_id, by, {"owner", "editor"})
        conn.execute(
            "UPDATE job_review_notes"
            " SET resolved = 1, resolved_at = ?, resolved_by = ?"
            " WHERE id = ?",
            (now, by, note_id),
        )
        conn.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        _record_activity(conn, job_id, "note-resolved", row["note"], by, now)
        row = _review_note_row(conn, note_id)
    return _dict(row)


def list_review_notes(
    job_id: int,
    *,
    user_email: str,
    include_resolved: bool = True,
) -> list[dict[str, Any]]:
    db.init_schema()
    resolved_clause = "" if include_resolved else " AND resolved = 0"
    with db.connect() as conn:
        _require_role(conn, job_id, user_email, {"owner", "editor", "viewer"})
        rows = conn.execute(
            "SELECT * FROM job_review_notes WHERE job_id = ?"
            + resolved_clause
            + " ORDER BY resolved, id",
            (job_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def _job_row(conn, job_id: int):
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def _review_note_row(conn, note_id: int):
    return conn.execute(
        "SELECT * FROM job_review_notes WHERE id = ?",
        (note_id,),
    ).fetchone()


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


def _require_role(
    conn,
    job_id: int,
    user_email: str,
    allowed: set[str],
) -> str:
    row = _access_row(conn, job_id, user_email)
    if row is None or row["role"] not in allowed:
        raise JobError("job access denied")
    return row["role"]


def _record_activity(
    conn,
    job_id: int,
    kind: str,
    message: str,
    actor_email: str,
    now: str,
) -> None:
    conn.execute(
        "INSERT INTO job_activity(job_id, kind, message, actor_email, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (job_id, kind, message, actor_email, now),
    )


def _dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
