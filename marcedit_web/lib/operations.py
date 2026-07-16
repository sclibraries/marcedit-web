"""Durable operation queue read model (TASK-156)."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from . import db, sandbox


class OperationError(ValueError):
    """Raised when an operation action is missing or unauthorized."""


def operations_root() -> Path:
    return Path(
        os.environ.get("MARCEDIT_WEB_OPERATIONS_ROOT", "data/operations")
    )


def get_operation(operation_id: int) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id,)
        ).fetchone()
    if row is None:
        raise OperationError("operation not found")
    return _dict(row)


def list_visible_operations(user_email: str) -> list[dict[str, Any]]:
    """Return operations whose current source access includes the user."""
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT operations.* FROM operations"
            " LEFT JOIN job_access"
            " ON job_access.job_id=operations.job_id"
            " AND job_access.user_email=?"
            " WHERE (operations.job_id IS NULL"
            " AND operations.submitted_by=?)"
            " OR (operations.job_id IS NOT NULL"
            " AND job_access.user_email IS NOT NULL)"
            " ORDER BY operations.submitted_at DESC, operations.id DESC",
            (user_email, user_email),
        ).fetchall()
    return [_dict(row) for row in rows]


def list_artifacts(
    operation_id: int,
    user_email: str,
) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        _require_visible(conn, operation_id, user_email)
        rows = conn.execute(
            "SELECT * FROM operation_artifacts"
            " WHERE operation_id=? ORDER BY id",
            (operation_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def input_artifact(operation_id: int) -> dict[str, Any]:
    """Return the internal input artifact for a worker or submission service."""
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM operation_artifacts"
            " WHERE operation_id=? AND role='input' ORDER BY id LIMIT 1",
            (operation_id,),
        ).fetchone()
    if row is None:
        raise OperationError("input artifact not found")
    return _dict(row)


def list_events(
    operation_id: int,
    user_email: str,
) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        _require_visible(conn, operation_id, user_email)
        rows = conn.execute(
            "SELECT * FROM operation_events"
            " WHERE operation_id=? ORDER BY id",
            (operation_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def list_errors(
    operation_id: int,
    user_email: str,
) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        _require_visible(conn, operation_id, user_email)
        rows = conn.execute(
            "SELECT * FROM operation_errors"
            " WHERE operation_id=? ORDER BY ordinal"
            " LIMIT ?",
            (operation_id, sandbox.MAX_RETAINED_ERRORS),
        ).fetchall()
    return [_dict(row) for row in rows]


def _operation_row(
    conn: sqlite3.Connection,
    operation_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM operations WHERE id=?",
        (operation_id,),
    ).fetchone()


def _is_visible(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    user_email: str,
) -> bool:
    if row["job_id"] is None:
        return row["submitted_by"] == user_email
    access = conn.execute(
        "SELECT 1 FROM job_access WHERE job_id=? AND user_email=?",
        (row["job_id"], user_email),
    ).fetchone()
    return access is not None


def _require_visible(
    conn: sqlite3.Connection,
    operation_id: int,
    user_email: str,
) -> sqlite3.Row:
    row = _operation_row(conn, operation_id)
    if row is None or not _is_visible(conn, row, user_email):
        raise OperationError("operation not found")
    return row


def _append_event(
    conn: sqlite3.Connection,
    operation_id: int,
    *,
    kind: str,
    message: str,
    actor_email: str,
    created_at: str,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO operation_events(operation_id, kind, message,"
        " actor_email, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            operation_id,
            kind,
            message,
            actor_email,
            json.dumps(details or {}, sort_keys=True),
            created_at,
        ),
    )


def _dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
