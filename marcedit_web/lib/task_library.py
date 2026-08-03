"""Transactional folder and task-library primitives for TASK-193."""

from __future__ import annotations

from typing import Any

from . import audit, db


def _folder_dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _now() -> str:
    return db._utc_now_iso()  # noqa: SLF001 - shared DB timestamp contract


def _root_id(conn, *, scope: str, owner: str | None) -> int:
    if scope == "shared":
        row = conn.execute(
            "SELECT id FROM task_folders WHERE scope='shared'"
            " AND owner_email IS NULL AND parent_id IS NULL AND name='Unfiled'"
        ).fetchone()
        if row:
            return int(row["id"])
        now = _now()
        cur = conn.execute(
            "INSERT INTO task_folders"
            "(scope, owner_email, parent_id, name, created_by, created_at, updated_at)"
            " VALUES ('shared', NULL, NULL, 'Unfiled', '__runtime__', ?, ?)",
            (now, now),
        )
        return int(cur.lastrowid)
    if not owner:
        raise ValueError("personal folder owner is required")
    row = conn.execute(
        "SELECT id FROM task_folders WHERE scope='personal'"
        " AND owner_email=? AND parent_id IS NULL AND name='Unfiled'",
        (owner,),
    ).fetchone()
    if row:
        return int(row["id"])
    now = _now()
    cur = conn.execute(
        "INSERT INTO task_folders"
        "(scope, owner_email, parent_id, name, created_by, created_at, updated_at)"
        " VALUES ('personal', ?, NULL, 'Unfiled', ?, ?, ?)",
        (owner, owner, now, now),
    )
    return int(cur.lastrowid)


def ensure_task_folder(conn, *, owner: str, visibility: str) -> int:
    """Return a compatible Unfiled folder, creating a personal root if needed."""
    if visibility == "shared":
        return _root_id(conn, scope="shared", owner=None)
    if visibility == "private":
        return _root_id(conn, scope="personal", owner=owner)
    raise ValueError(f"invalid visibility {visibility!r}")


def list_folder_tree(user: str) -> list[dict[str, Any]]:
    """Return visible folders with visible task IDs, in stable tree order."""
    db.init_schema()
    with db.connect() as conn:
        rows = list(
            conn.execute(
                "SELECT * FROM task_folders WHERE"
                " (scope='shared' OR owner_email=?)"
                " ORDER BY scope, owner_email, parent_id, name COLLATE NOCASE",
                (user,),
            )
        )
        visible_tasks = list(
            conn.execute(
                "SELECT id, folder_id FROM tasks WHERE owner_email=?"
                " OR (visibility='shared' AND owner_email<>?)",
                (user, user),
            )
        )
    task_ids: dict[int, list[int]] = {}
    for task in visible_tasks:
        if task["folder_id"] is not None:
            task_ids.setdefault(int(task["folder_id"]), []).append(int(task["id"]))
    return [
        {**_folder_dict(row), "task_ids": sorted(task_ids.get(int(row["id"]), []))}
        for row in rows
    ]


def create_folder(
    actor: str,
    *,
    scope: str,
    parent_id: int | None,
    name: str,
) -> dict[str, Any]:
    """Create a personal/shared folder with bounded parent validation."""
    name = str(name).strip()
    if scope not in {"personal", "shared"}:
        raise ValueError("folder scope must be personal or shared")
    if not name or len(name) > 255:
        raise ValueError("folder name must contain 1-255 characters")
    with db.connect() as conn:
        if parent_id is None:
            parent_id = _root_id(
                conn,
                scope=scope,
                owner=None if scope == "shared" else actor,
            )
        parent = conn.execute(
            "SELECT * FROM task_folders WHERE id=?", (parent_id,)
        ).fetchone()
        if parent is None or parent["scope"] != scope:
            raise ValueError(f"{scope} folder parent is not accessible")
        if scope == "personal" and parent["owner_email"] != actor:
            raise ValueError("personal folder parent is not accessible")
        depth = 1
        seen: set[int] = set()
        current = parent
        while current["parent_id"] is not None:
            current_id = int(current["id"])
            if current_id in seen:
                raise ValueError("folder cycle detected")
            seen.add(current_id)
            depth += 1
            if depth > 3:
                raise ValueError("folder depth exceeds three levels")
            current = conn.execute(
                "SELECT * FROM task_folders WHERE id=?", (current["parent_id"],)
            ).fetchone()
            if current is None:
                raise ValueError(f"{scope} folder parent is not accessible")
        now = _now()
        try:
            cur = conn.execute(
                "INSERT INTO task_folders"
                "(scope, owner_email, parent_id, name, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    scope,
                    None if scope == "shared" else actor,
                    parent_id,
                    name,
                    actor,
                    now,
                    now,
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("folder name already exists under this parent") from exc
            raise
        row = conn.execute(
            "SELECT * FROM task_folders WHERE id=?", (cur.lastrowid,)
        ).fetchone()
    audit.audit_event(
        "task-folder-created",
        user=actor,
        folder_id=row["id"],
        scope=scope,
        parent_id=parent_id,
        name=name,
    )
    return _folder_dict(row)

