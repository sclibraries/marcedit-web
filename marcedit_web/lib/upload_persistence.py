"""Per-OAuth-user upload persistence across browser refresh (TASK-051).

The uploads pipeline already disk-backs each session's bytes in
``/tmp/marcedit-web-records-*``, but ``st.session_state`` is wiped
on a hard browser refresh, so the loaded batch appears lost.

For signed-in users we additionally:

1. Write the raw upload to a stable per-user path under
   ``data/uploads/<safe_user_slug>/upload.mrc``.
2. Insert a row in the ``uploads`` SQL table with metadata:
   filename, record count, byte count, timestamp, active flag.

On next session init, if a row exists with ``active=1`` and the
on-disk file still exists, the session rehydrates from it (see
``session.restore_active_upload``).

Anonymous (not-signed-in) users are intentionally excluded — refresh
loses their upload. The product decision (see TASK-051 ticket) is
"sign in to keep your work" rather than minting a session cookie
for anonymous users.

Concurrency: each user has at most one ``active=1`` row at a time.
``record_upload`` flips any prior active row to 0 before inserting
the new one. The DB write is atomic within a single transaction.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path
from typing import Any

from . import db, jobs
from .identity import ANONYMOUS, is_anonymous
from .task_storage import safe_user_slug

logger = logging.getLogger("marcedit_web.upload_persistence")


def _uploads_root() -> Path:
    """Root for persisted uploads.

    Lives under the same ``data/`` mount the audit log and DB use, so
    operators only need to mount one host directory. Override via
    ``MARCEDIT_WEB_UPLOADS_ROOT`` for tests / alternate deployments.
    """
    override = os.environ.get("MARCEDIT_WEB_UPLOADS_ROOT")
    if override:
        return Path(override)
    return Path("data/uploads")


def persisted_upload_dir(user: str) -> Path:
    """Stable per-user directory for the active upload file.

    Returns ``data/uploads/<safe_slug>/``. Created on demand.
    The actual file is always written as ``upload.mrc`` inside this
    dir — matches the existing ``RecordStore.from_bytes`` contract.
    """
    path = _uploads_root() / safe_user_slug(user)
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_upload(
    *,
    user: str,
    filename: str,
    file_path: Path | str,
    record_count: int,
    file_bytes: int,
    job_id: int | None = None,
) -> None:
    """Mark ``file_path`` as ``user``'s active upload.

    No-op for anonymous users. Flips any prior active row for this
    user to 0 in the same transaction so the table never has two
    active rows for the same identity.
    """
    if is_anonymous(user):
        return
    now = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    target_job_id = job_id or jobs.ensure_default_job(user)["id"]
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE uploads SET active = 0 WHERE user_email = ? AND active = 1",
            (user,),
        )
        conn.execute(
            "INSERT INTO uploads"
            "(user_email, job_id, filename, file_path, record_count, file_bytes,"
            " uploaded_at, active)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (
                user,
                target_job_id,
                filename,
                str(file_path),
                record_count,
                file_bytes,
                now,
            ),
        )


def get_active_upload(user: str) -> dict[str, Any] | None:
    """Return the active upload row for ``user`` as a dict, or None.

    No-op for anonymous users — they never have rows in this table.
    The caller is expected to verify the file actually exists on
    disk (it might have been swept by a /tmp cleanup or a backup
    restore); when the file is gone, call ``clear_active_upload``.
    """
    if is_anonymous(user):
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM uploads"
            " WHERE user_email = ? AND active = 1"
            " ORDER BY id DESC LIMIT 1",
            (user,),
        ).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def clear_active_upload(user: str) -> None:
    """Drop the user's active upload — file + row.

    No-op for anonymous users. Unlinks the on-disk file
    best-effort; failure to remove the file still flips the row.
    """
    if is_anonymous(user):
        return
    row = get_active_upload(user)
    if row is None:
        return
    file_path = Path(row["file_path"])
    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "could not remove persisted upload %s: %s", file_path, exc
        )
    with db.connect() as conn:
        conn.execute(
            "UPDATE uploads SET active = 0"
            " WHERE user_email = ? AND active = 1",
            (user,),
        )
