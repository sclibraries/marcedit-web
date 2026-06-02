"""SQL-backed task storage with private/shared visibility (TASK-050).

Tasks live in the ``tasks`` SQLite table. Each row has an
``owner_email`` (the OAuth/Shibboleth identity of the author, or
``__shared__`` sentinel for legacy shared-dir migrations) and a
``visibility`` flag of ``'private'`` or ``'shared'``.

Visibility rules:

* **private** — only the owner sees the task in their list and can
  edit / delete it.
* **shared** — every user sees the task; only the owner can edit or
  delete it. Other users see it as a read-only registered task they
  can run against their batches.

The Python task loader (``lib/tasks.load_user_tasks``) still needs
``.py`` files on disk because Python's importlib wants a file path.
``materialize_to_dir(user, target)`` writes each visible task as a
file under ``target/`` using the existing
``editor.serialize_user_task`` so the on-disk shape is identical to
what the legacy filesystem path produced. The Tasks page materializes
into a per-session ``/tmp/marcedit-web-tasks-<sid>/`` directory on
every render — cheap because the importer's mtime guard prevents
re-parsing unchanged files.

Why not write source code directly to the loader? The loader does
AST parsing against an on-disk file (TASK-029 security review); the
read-from-file contract is enforced by the importer in
``marcedit_web.lib.tasks``. Materializing keeps that contract intact
without rewriting the importer.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any, Iterable

from . import db, editor

logger = logging.getLogger("marcedit_web.task_db")


def _utc_now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def save_task(
    *,
    owner: str,
    name: str,
    description: str,
    body: str,
    extra_imports: Iterable[str] | None = None,
    visibility: str = "private",
) -> None:
    """Upsert a task row by (owner, name).

    ``visibility`` must be ``'private'`` or ``'shared'`` (the DB
    constraint enforces this; callers should validate via the UI).
    ``extra_imports`` lines are joined by newline for storage.
    """
    if not editor.is_valid_slug(name):
        raise ValueError(
            f"invalid task name {name!r}: use lowercase letters, "
            "digits, and hyphens"
        )
    if visibility not in {"private", "shared"}:
        raise ValueError(f"invalid visibility {visibility!r}")
    extras = "\n".join(extra_imports or [])
    now = _utc_now()
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM tasks WHERE owner_email = ? AND name = ?",
            (owner, name),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO tasks"
                "(owner_email, name, description, body, extra_imports,"
                " visibility, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (owner, name, description, body, extras, visibility, now, now),
            )
        else:
            conn.execute(
                "UPDATE tasks SET description = ?, body = ?,"
                " extra_imports = ?, visibility = ?, updated_at = ?"
                " WHERE owner_email = ? AND name = ?",
                (description, body, extras, visibility, now, owner, name),
            )


def get_task(owner: str, name: str) -> dict[str, Any] | None:
    """Return a single task row as a dict, or None if it doesn't exist."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE owner_email = ? AND name = ?",
            (owner, name),
        ).fetchone()
    return _row_to_dict(row)


def delete_task(owner: str, name: str) -> bool:
    """Delete a task. Returns True iff a row was removed."""
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM tasks WHERE owner_email = ? AND name = ?",
            (owner, name),
        )
        return cur.rowcount > 0


def set_visibility(owner: str, name: str, visibility: str) -> None:
    """Flip a task's visibility (private/shared) in place."""
    if visibility not in {"private", "shared"}:
        raise ValueError(f"invalid visibility {visibility!r}")
    now = _utc_now()
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET visibility = ?, updated_at = ?"
            " WHERE owner_email = ? AND name = ?",
            (visibility, now, owner, name),
        )


def list_visible_tasks(user: str) -> list[dict[str, Any]]:
    """Return every task ``user`` should see.

    Includes:
      * Every row where ``owner_email = user`` (regardless of
        visibility — the owner sees their own private tasks).
      * Every row where ``visibility = 'shared'`` AND
        ``owner_email != user`` (don't double-count the user's own
        shared tasks).

    Sorted by name for stable UI rendering.
    """
    with db.connect() as conn:
        rows = list(conn.execute(
            "SELECT * FROM tasks"
            " WHERE owner_email = ?"
            " OR (visibility = 'shared' AND owner_email != ?)"
            " ORDER BY name",
            (user, user),
        ))
    return [_row_to_dict(r) for r in rows]


def list_own_tasks(user: str) -> list[dict[str, Any]]:
    """Return only tasks ``user`` owns (regardless of visibility)."""
    with db.connect() as conn:
        rows = list(conn.execute(
            "SELECT * FROM tasks WHERE owner_email = ? ORDER BY name",
            (user,),
        ))
    return [_row_to_dict(r) for r in rows]


def count_visible(user: str) -> dict[str, int]:
    """Counts for the Tasks-page metrics bar.

    Returns ``{"own": N, "shared_from_others": M}`` — sharing what
    the user owns isn't double-counted on the "shared" side.
    """
    with db.connect() as conn:
        own = conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE owner_email = ?",
            (user,),
        ).fetchone()["n"]
        shared = conn.execute(
            "SELECT COUNT(*) AS n FROM tasks"
            " WHERE visibility = 'shared' AND owner_email != ?",
            (user,),
        ).fetchone()["n"]
    return {"own": own, "shared_from_others": shared}


def materialize_to_dir(user: str, target_dir: Path) -> int:
    """Write each visible task as a ``.py`` file under ``target_dir``.

    Each file uses ``editor.serialize_user_task`` so the on-disk
    shape matches what the legacy filesystem store produced.
    ``target_dir`` is created if missing.

    Returns the count of files written. Cheap to call on every
    page render — the loader's mtime guard prevents repeat parses
    for files whose content didn't change.

    A file already in ``target_dir`` that no longer corresponds to
    a visible task is removed, so a deleted/unshared task vanishes
    from the importer's view too.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    visible = list_visible_tasks(user)
    desired_names = {editor.task_file_path(target_dir, t["name"]).name for t in visible}

    # Drop stale .py files (tasks that disappeared since the last
    # materialization). Leave non-.py files alone — operators may
    # park notes in the dir.
    for stale in target_dir.glob("*.py"):
        if stale.name not in desired_names:
            try:
                stale.unlink()
            except OSError:
                logger.warning("could not remove stale task file %s", stale)

    written = 0
    for t in visible:
        extras = [
            line for line in (t.get("extra_imports") or "").split("\n") if line
        ]
        content = editor.serialize_user_task(
            t["name"],
            t["description"],
            t["body"],
            extra_imports=extras or None,
        )
        path = editor.task_file_path(target_dir, t["name"])
        existing = path.read_text() if path.exists() else None
        if existing != content:
            # Only rewrite when bytes change — preserves mtime for
            # tasks whose content is unchanged so the importer's
            # freshness check stays accurate.
            path.write_text(content)
        written += 1
    return written


def _row_to_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
