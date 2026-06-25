"""Persisted undo/provenance snapshots for job-scoped changes."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import db

DEFAULT_SNAPSHOT_CAP = 20


def snapshots_root() -> Path:
    override = os.environ.get("MARCEDIT_WEB_SNAPSHOTS_ROOT")
    return Path(override) if override else Path("data/snapshots")


def create_snapshot(
    *,
    job_id: int,
    user_email: str,
    kind: str,
    label: str,
    before_bytes: bytes,
    after_bytes: bytes,
    summary: dict[str, Any] | None = None,
    cap: int = DEFAULT_SNAPSHOT_CAP,
) -> dict[str, Any]:
    """Persist one before/after snapshot and return the DB row."""
    if cap < 1:
        raise ValueError("cap must be at least 1")
    db.init_schema()
    created_at = _utc_now_iso()
    snap_dir = snapshots_root() / str(job_id)
    snap_dir.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    before_path = snap_dir / f"{token}-before.mrc"
    after_path = snap_dir / f"{token}-after.mrc"
    before_path.write_bytes(before_bytes)
    after_path.write_bytes(after_bytes)
    summary_json = json.dumps(summary or {}, sort_keys=True)

    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO job_snapshots(job_id, user_email, kind, label,"
            " before_path, after_path, summary_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                user_email,
                kind,
                label,
                str(before_path),
                str(after_path),
                summary_json,
                created_at,
            ),
        )
        snapshot_id = int(cur.lastrowid)
        row = _snapshot_row(conn, snapshot_id)
    _prune_to_cap(job_id, cap)
    with db.connect() as conn:
        row = _snapshot_row(conn, snapshot_id)
    return _dict(row)


def list_snapshots(job_id: int) -> list[dict[str, Any]]:
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM job_snapshots"
            " WHERE job_id = ?"
            " ORDER BY id DESC",
            (job_id,),
        ).fetchall()
    return [_dict(row) for row in rows]


def restore_bytes(snapshot_id: int) -> bytes:
    """Return the pre-change bytes for ``snapshot_id``."""
    db.init_schema()
    with db.connect() as conn:
        row = _snapshot_row(conn, snapshot_id)
    if row is None:
        raise KeyError(f"snapshot not found: {snapshot_id}")
    return Path(row["before_path"]).read_bytes()


def _prune_to_cap(job_id: int, cap: int) -> None:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM job_snapshots"
            " WHERE job_id = ?"
            " ORDER BY id DESC",
            (job_id,),
        ).fetchall()
        victims = rows[cap:]
        for row in victims:
            _unlink_snapshot_files(row)
            conn.execute("DELETE FROM job_snapshots WHERE id = ?", (row["id"],))


def _unlink_snapshot_files(row) -> None:
    for key in ("before_path", "after_path"):
        try:
            Path(row[key]).unlink()
        except FileNotFoundError:
            pass


def _snapshot_row(conn, snapshot_id: int):
    return conn.execute(
        "SELECT * FROM job_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()


def _dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
