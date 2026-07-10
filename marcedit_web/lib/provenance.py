"""Persisted undo/provenance snapshots for job-scoped changes."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import db

DEFAULT_SNAPSHOT_CAP = 20
_COPY_CHUNK_BYTES = 1024 * 1024


def snapshots_root() -> Path:
    override = os.environ.get("MARCEDIT_WEB_SNAPSHOTS_ROOT")
    return Path(override) if override else Path("data/snapshots")


def create_snapshot(
    *,
    job_id: int,
    user_email: str,
    kind: str,
    label: str,
    before_path: Path | None = None,
    after_path: Path | None = None,
    before_bytes: bytes | None = None,
    after_bytes: bytes | None = None,
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
    snapshot_before_path = snap_dir / f"{token}-before.mrc"
    snapshot_after_path = snap_dir / f"{token}-after.mrc"
    try:
        _write_snapshot_file(
            snapshot_before_path,
            source_path=before_path,
            source_bytes=before_bytes,
            label="before",
        )
        _write_snapshot_file(
            snapshot_after_path,
            source_path=after_path,
            source_bytes=after_bytes,
            label="after",
        )
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
                    str(snapshot_before_path),
                    str(snapshot_after_path),
                    summary_json,
                    created_at,
                ),
            )
            snapshot_id = int(cur.lastrowid)
    except Exception:
        snapshot_before_path.unlink(missing_ok=True)
        snapshot_after_path.unlink(missing_ok=True)
        raise
    _prune_to_cap(job_id, cap)
    with db.connect() as conn:
        row = _snapshot_row(conn, snapshot_id)
    return _dict(row)


def _write_snapshot_file(
    destination: Path,
    *,
    source_path: Path | None,
    source_bytes: bytes | None,
    label: str,
) -> None:
    if (source_path is None) == (source_bytes is None):
        raise ValueError(f"provide exactly one {label} snapshot source")
    if source_path is not None:
        with Path(source_path).open("rb") as source, destination.open(
            "wb"
        ) as target:
            shutil.copyfileobj(source, target, _COPY_CHUNK_BYTES)
        return
    destination.write_bytes(source_bytes or b"")


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
    return restore_path(snapshot_id).read_bytes()


def restore_path(snapshot_id: int) -> Path:
    """Return the durable pre-change MRC path for ``snapshot_id``."""
    db.init_schema()
    with db.connect() as conn:
        row = _snapshot_row(conn, snapshot_id)
    if row is None:
        raise KeyError(f"snapshot not found: {snapshot_id}")
    return Path(row["before_path"])


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
