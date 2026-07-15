"""Collaboration checkout and version helpers (TASK-094)."""

from __future__ import annotations

import datetime as dt

from typing import Any

from . import db, job_files, jobs, locks


class CollaborationError(ValueError):
    """Raised when a collaboration save/check-out invariant fails."""


def acquire_file_checkout(
    file_id: int,
    user_email: str,
    ttl_seconds: int = 1800,
) -> locks.LockDecision:
    """Acquire or renew the exclusive checkout for one job file."""
    db.init_schema()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        now = _now()
        now_iso = _iso(now)
        file_row = _file_for_user_in_tx(conn, file_id, user_email)
        if file_row["access_role"] not in {"owner", "editor"}:
            raise CollaborationError("owner or editor access required")
        if file_row["archived_at"] is not None:
            raise CollaborationError("archived files cannot be checked out")
        decision = _acquire_lock_in_tx(
            conn,
            "job-file",
            str(file_id),
            user_email,
            _iso(now + dt.timedelta(seconds=ttl_seconds)),
            now_iso,
            now,
        )
        if decision.acquired and file_row["status"] in {
            "new",
            "changes_requested",
        }:
            _set_file_status_in_tx(
                conn,
                file_row,
                "in_progress",
                user_email,
                now_iso,
            )
        return decision


def release_file_checkout(file_id: int, user_email: str) -> bool:
    """Release a file checkout only when ``user_email`` holds it."""
    return locks.release_lock("job-file", str(file_id), user_email)


def return_file_for_review(
    file_id: int,
    user_email: str,
    opened_version_id: int,
) -> bool:
    """Move a held file to review and release its checkout atomically."""
    db.init_schema()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        now_iso = _iso(_now())
        file_row = _file_for_user_in_tx(conn, file_id, user_email)
        if file_row["access_role"] not in {"owner", "editor"}:
            raise CollaborationError("owner or editor access required")
        if file_row["archived_at"] is not None:
            raise CollaborationError("archived files cannot be returned for review")
        _assert_file_checkout_in_tx(
            conn,
            file_id,
            user_email,
            opened_version_id,
        )
        if file_row["status"] != "in_progress":
            raise CollaborationError(
                "only an in-progress file can be returned for review"
            )
        _set_file_status_in_tx(
            conn,
            file_row,
            "needs_review",
            user_email,
            now_iso,
        )
        conn.execute(
            "DELETE FROM advisory_locks"
            " WHERE resource_type='job-file' AND resource_id=?"
            " AND holder_email=?",
            (str(file_id), user_email),
        )
    return True


def force_release_file_checkout(file_id: int, by: str) -> bool:
    """Force-release one file checkout as the parent-job owner."""
    file_row = _file_for_user(file_id, by)
    try:
        jobs.require_role(int(file_row["job_id"]), by, {"owner"})
    except jobs.JobError as exc:
        raise CollaborationError("only the job owner can force release") from exc
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row = conn.execute(
            "SELECT holder_email FROM advisory_locks"
            " WHERE resource_type='job-file' AND resource_id=?",
            (str(file_id),),
        ).fetchone()
        if lock_row is None:
            return False
        conn.execute(
            "DELETE FROM advisory_locks"
            " WHERE resource_type='job-file' AND resource_id=?",
            (str(file_id),),
        )
        jobs._record_activity(  # noqa: SLF001 - shared transaction helper
            conn,
            int(file_row["job_id"]),
            "job-file-checkout-force-released",
            f"Force-released checkout held by {lock_row['holder_email']}",
            by,
            now,
            job_file_id=file_id,
        )
    return True


def _assert_file_checkout_in_tx(
    conn,
    file_id: int,
    user_email: str,
    opened_version_id: int,
) -> None:
    """Require the actor's active checkout and exact opened file version."""
    row = _active_lock_row(conn, "job-file", str(file_id), _now())
    if row is None or row["holder_email"] != user_email:
        raise CollaborationError("file checkout is not held by this user")
    current = conn.execute(
        "SELECT current_version_id FROM job_files WHERE id=?",
        (file_id,),
    ).fetchone()
    if current is None or int(current["current_version_id"]) != opened_version_id:
        raise CollaborationError("file changed since this version was opened")


def record_resource_id(job_id: int, record_index: int) -> str:
    """Return the 1-based record lock key for ``job_id``/``record_index``."""
    return f"{job_id}:{record_index}"


def acquire_record_lock(
    job_id: int,
    record_index: int,
    user_email: str,
    ttl_seconds: int = 900,
) -> locks.LockDecision:
    """Acquire a legacy record lock for paths not yet backed by a job file.

    Deprecated for file-backed mutation paths; use ``acquire_file_checkout``.
    """
    _require_editor(job_id, user_email)
    now = _now()
    expires_at = _iso(now + dt.timedelta(seconds=ttl_seconds))
    now_iso = _iso(now)
    resource_id = record_resource_id(job_id, record_index)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job_lock = _active_lock_row(conn, "job", str(job_id), now)
        if job_lock is not None:
            return locks.LockDecision(
                False,
                job_lock["holder_email"],
                job_lock["expires_at"],
            )
        return _acquire_lock_in_tx(
            conn,
            "record",
            resource_id,
            user_email,
            expires_at,
            now_iso,
            now,
        )


def acquire_job_lock(
    job_id: int,
    user_email: str,
    ttl_seconds: int = 1800,
) -> locks.LockDecision:
    """Acquire a legacy job lock for paths not yet backed by a job file.

    Deprecated for file-backed mutation paths; use ``acquire_file_checkout``.
    """
    _require_editor(job_id, user_email)
    now = _now()
    expires_at = _iso(now + dt.timedelta(seconds=ttl_seconds))
    now_iso = _iso(now)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        record_lock = _active_record_lock_for_job(conn, job_id, now)
        if record_lock is not None:
            return locks.LockDecision(
                False,
                record_lock["holder_email"],
                record_lock["expires_at"],
            )
        return _acquire_lock_in_tx(
            conn,
            "job",
            str(job_id),
            user_email,
            expires_at,
            now_iso,
            now,
        )


def release_record_lock(job_id: int, record_index: int, user_email: str) -> bool:
    return locks.release_lock(
        "record",
        record_resource_id(job_id, record_index),
        user_email,
    )


def release_job_lock(job_id: int, user_email: str) -> bool:
    return locks.release_lock("job", str(job_id), user_email)


def assert_can_save_record(
    job_id: int,
    record_index: int,
    user_email: str,
    opened_version: int,
) -> None:
    """Fail unless ``user_email`` still owns the record lock and version."""
    _require_editor(job_id, user_email)
    now = _now()
    resource_id = record_resource_id(job_id, record_index)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _active_lock_row(conn, "record", resource_id, now)
        if row is None or row["holder_email"] != user_email:
            raise CollaborationError("record lock is not held by this user")
        current = _ensure_version_row(conn, job_id)
        if current != opened_version:
            raise CollaborationError("job changed since this record was opened")


def current_job_version(job_id: int) -> int:
    """Return the current mutation version for ``job_id``."""
    db.init_schema()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _ensure_version_row(conn, job_id)


def bump_job_version(job_id: int) -> int:
    """Increment and return the current mutation version for ``job_id``."""
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = _ensure_version_row(conn, job_id)
        next_version = current + 1
        conn.execute(
            "UPDATE job_versions SET version = ?, updated_at = ?"
            " WHERE job_id = ?",
            (next_version, now, job_id),
        )
    return next_version


def _ensure_version_row(conn, job_id: int) -> int:
    row = conn.execute(
        "SELECT version FROM job_versions WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is not None:
        return int(row["version"])
    conn.execute(
        "INSERT INTO job_versions(job_id, version, updated_at)"
        " VALUES (?, 0, ?)",
        (job_id, _utc_now_iso()),
    )
    return 0


def _require_editor(job_id: int, user_email: str) -> str:
    try:
        return jobs.require_role(job_id, user_email, {"owner", "editor"})
    except jobs.JobError as exc:
        raise CollaborationError("owner or editor access required") from exc


def _file_for_user(file_id: int, user_email: str) -> dict[str, Any]:
    try:
        return job_files.get_file(file_id, user_email)
    except job_files.JobFileError as exc:
        raise CollaborationError("job file access required") from exc


def _file_for_user_in_tx(conn, file_id: int, user_email: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT job_files.*, job_access.role AS access_role"
        " FROM job_files"
        " JOIN job_access ON job_access.job_id=job_files.job_id"
        " WHERE job_files.id=? AND job_access.user_email=?",
        (file_id, user_email.strip().lower()),
    ).fetchone()
    if row is None:
        raise CollaborationError("job file access required")
    return {key: row[key] for key in row.keys()}


def _set_file_status_in_tx(
    conn,
    file_row: dict[str, Any],
    status: str,
    user_email: str,
    now: str,
) -> None:
    file_id = int(file_row["id"])
    conn.execute(
        "UPDATE job_files SET status=?, updated_by=?, updated_at=? WHERE id=?",
        (status, user_email, now, file_id),
    )
    jobs._record_activity(  # noqa: SLF001 - shared transaction helper
        conn,
        int(file_row["job_id"]),
        "job-file-status-changed",
        f"{file_row['display_name']} status changed to {status}",
        user_email,
        now,
        job_file_id=file_id,
    )


def _acquire_lock_in_tx(
    conn,
    resource_type: str,
    resource_id: str,
    holder: str,
    expires_at: str,
    now_iso: str,
    now: dt.datetime,
) -> locks.LockDecision:
    row = conn.execute(
        "SELECT holder_email, expires_at FROM advisory_locks"
        " WHERE resource_type = ? AND resource_id = ?",
        (resource_type, resource_id),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO advisory_locks"
            "(resource_type, resource_id, holder_email, expires_at,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (resource_type, resource_id, holder, expires_at, now_iso, now_iso),
        )
        return locks.LockDecision(True, holder, expires_at)
    if row["holder_email"] == holder and _parse_iso(row["expires_at"]) > now:
        conn.execute(
            "UPDATE advisory_locks"
            " SET holder_email = ?, expires_at = ?, updated_at = ?"
            " WHERE resource_type = ? AND resource_id = ?",
            (holder, expires_at, now_iso, resource_type, resource_id),
        )
        return locks.LockDecision(True, holder, expires_at, renewed=True)
    if _parse_iso(row["expires_at"]) <= now:
        conn.execute(
            "UPDATE advisory_locks"
            " SET holder_email = ?, expires_at = ?, updated_at = ?"
            " WHERE resource_type = ? AND resource_id = ?",
            (holder, expires_at, now_iso, resource_type, resource_id),
        )
        return locks.LockDecision(True, holder, expires_at)
    return locks.LockDecision(False, row["holder_email"], row["expires_at"])


def _active_lock_row(
    conn,
    resource_type: str,
    resource_id: str,
    now: dt.datetime,
) -> Any | None:
    row = conn.execute(
        "SELECT holder_email, expires_at FROM advisory_locks"
        " WHERE resource_type = ? AND resource_id = ?",
        (resource_type, resource_id),
    ).fetchone()
    if row is None or _parse_iso(row["expires_at"]) <= now:
        return None
    return row


def _active_record_lock_for_job(conn, job_id: int, now: dt.datetime) -> Any | None:
    rows = conn.execute(
        "SELECT holder_email, expires_at FROM advisory_locks"
        " WHERE resource_type = 'record' AND resource_id LIKE ?",
        (f"{job_id}:%",),
    ).fetchall()
    for row in rows:
        if _parse_iso(row["expires_at"]) > now:
            return row
    return None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _iso(value: dt.datetime) -> str:
    return value.isoformat(timespec="seconds") + "Z"


def _parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.removesuffix("Z"))


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
