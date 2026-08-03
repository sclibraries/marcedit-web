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
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import audit, db, editor, native_tasks

logger = logging.getLogger("marcedit_web.task_db")


class NativeTaskStorageError(RuntimeError):
    pass


class NativeTaskConflict(NativeTaskStorageError):
    pass


class NativeTaskCompatibilityError(NativeTaskStorageError):
    pass


class NativeTaskIntegrityError(NativeTaskStorageError):
    pass


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
        from . import task_library

        folder_id = task_library.ensure_task_folder(
            conn, owner=owner, visibility=visibility
        )
        existing = conn.execute(
            "SELECT created_at, definition_json, folder_id FROM tasks"
            " WHERE owner_email = ? AND name = ?",
            (owner, name),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO tasks"
                "(owner_email, name, description, body, extra_imports,"
                " visibility, folder_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (owner, name, description, body, extras, visibility, folder_id, now, now),
            )
        else:
            if existing["definition_json"] is not None:
                raise NativeTaskStorageError(
                    "native tasks must be saved through the native task API"
                )
            cursor = conn.execute(
                "UPDATE tasks SET description = ?, body = ?,"
                " extra_imports = ?, visibility = ?, folder_id = COALESCE(folder_id, ?),"
                " revision = revision + 1,"
                " updated_at = ?"
                " WHERE owner_email = ? AND name = ?"
                " AND definition_json IS NULL",
                (description, body, extras, visibility, folder_id, now, owner, name),
            )
            if cursor.rowcount != 1:
                raise NativeTaskStorageError(
                    "native tasks must be saved through the native task API"
                )


def save_native_task(
    *,
    owner: str,
    definition: Mapping[str, Any],
    visibility: str = "private",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Atomically store a validated native definition and compiled snapshots."""
    if visibility not in {"private", "shared"}:
        raise ValueError(f"invalid visibility {visibility!r}")

    valid = native_tasks.validate_definition(definition)
    definition_json = native_tasks.canonical_definition_json(valid)
    compiled = native_tasks.compile_definition(valid)
    compiler_fingerprint = native_tasks.current_compiler_fingerprint()
    name = valid["name"]
    description = valid["description"]
    extra_imports = "\n".join(compiled.imports)
    now = _utc_now()

    with db.connect() as conn:
        existing = conn.execute(
            "SELECT revision FROM tasks WHERE owner_email = ? AND name = ?",
            (owner, name),
        ).fetchone()
        if existing is None:
            if expected_revision is not None:
                raise NativeTaskConflict(
                    f"expected revision {expected_revision} for missing task"
                )
            try:
                conn.execute(
                    "INSERT INTO tasks"
                    "(owner_email, name, description, body, extra_imports,"
                    " definition_json, compiler_fingerprint, visibility,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        owner,
                        name,
                        description,
                        compiled.body,
                        extra_imports,
                        definition_json,
                        compiler_fingerprint,
                        visibility,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise NativeTaskConflict(
                    "task changed before the expected revision could be saved"
                ) from exc
        else:
            if expected_revision is None:
                raise NativeTaskConflict(
                    "expected revision is required to update an existing task"
                )
            cursor = conn.execute(
                "UPDATE tasks"
                " SET description = ?,"
                " body = ?,"
                " extra_imports = ?,"
                " definition_json = ?,"
                " compiler_fingerprint = ?,"
                " visibility = ?,"
                " revision = revision + 1,"
                " updated_at = ?"
                " WHERE owner_email = ? AND name = ? AND revision = ?",
                (
                    description,
                    compiled.body,
                    extra_imports,
                    definition_json,
                    compiler_fingerprint,
                    visibility,
                    now,
                    owner,
                    name,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise NativeTaskConflict(
                    f"task no longer has expected revision {expected_revision}"
                )
        row = conn.execute(
            "SELECT * FROM tasks WHERE owner_email = ? AND name = ?",
            (owner, name),
        ).fetchone()
    return _row_to_dict(row)


def get_task(owner: str, name: str) -> dict[str, Any] | None:
    """Return a single task row as a dict, or None if it doesn't exist."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE owner_email = ? AND name = ?",
            (owner, name),
        ).fetchone()
    return _row_to_dict(row)


def prepare_task_for_execution(
    owner: str,
    name: str,
    *,
    audit_user: str,
) -> dict[str, Any]:
    """Verify or migrate a task's native compiler snapshots before execution."""
    row = get_task(owner, name)
    if row is None:
        raise NativeTaskCompatibilityError(
            f"native task not found: {owner}/{name}"
        )
    if row["definition_json"] is None:
        return row

    try:
        definition = native_tasks.load_definition_json(row["definition_json"])
        compiled = native_tasks.compile_definition(definition)
        current_fingerprint = native_tasks.current_compiler_fingerprint()
    except (ValueError, native_tasks.CompilerContractError) as exc:
        raise NativeTaskCompatibilityError(str(exc)) from exc

    compiled_imports = "\n".join(compiled.imports)
    if row["compiler_fingerprint"] == current_fingerprint:
        for column, expected in (
            ("body", compiled.body),
            ("extra_imports", compiled_imports),
        ):
            if row[column] != expected:
                raise NativeTaskIntegrityError(
                    f"native task {column} snapshot does not match"
                    " the current compiler"
                )
        return row

    now = _utc_now()
    with db.connect() as conn:
        cursor = conn.execute(
            "UPDATE tasks"
            " SET body = ?,"
            " extra_imports = ?,"
            " compiler_fingerprint = ?,"
            " revision = revision + 1,"
            " updated_at = ?"
            " WHERE id = ? AND revision = ? AND definition_json = ?",
            (
                compiled.body,
                compiled_imports,
                current_fingerprint,
                now,
                row["id"],
                row["revision"],
                row["definition_json"],
            ),
        )
        if cursor.rowcount != 1:
            raise NativeTaskCompatibilityError(
                "native task changed during compiler migration"
            )
        migrated = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (row["id"],),
        ).fetchone()
    prepared = _row_to_dict(migrated)
    audit.audit_event(
        "native-task-compiler-migrated",
        user=audit_user,
        owner=row["owner_email"],
        task_name=row["name"],
        old_fingerprint=row["compiler_fingerprint"],
        new_fingerprint=current_fingerprint,
    )
    return prepared


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
            "UPDATE tasks SET visibility = ?, revision = revision + 1,"
            " updated_at = ?"
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
        if t.get("definition_json") is not None:
            path = editor.task_file_path(target_dir, t["name"])
            try:
                execution_row = prepare_task_for_execution(
                    t["owner_email"],
                    t["name"],
                    audit_user=user,
                )
            except (NativeTaskCompatibilityError, NativeTaskIntegrityError):
                path.unlink(missing_ok=True)
                raise
        else:
            execution_row = t
        extras = [
            line
            for line in (execution_row.get("extra_imports") or "").split("\n")
            if line
        ]
        content = editor.serialize_user_task(
            execution_row["name"],
            execution_row["description"],
            execution_row["body"],
            extra_imports=extras or None,
        )
        path = editor.task_file_path(target_dir, execution_row["name"])
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
