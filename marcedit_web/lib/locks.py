"""SQLite advisory locks for collaboration foundations (TASK-083)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from . import db


@dataclass(frozen=True)
class LockDecision:
    acquired: bool
    holder_email: str | None = None
    expires_at: str | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _iso(value: dt.datetime) -> str:
    return value.isoformat(timespec="seconds") + "Z"


def _parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.removesuffix("Z"))


def acquire_lock(
    resource_type: str,
    resource_id: str,
    holder: str,
    ttl_seconds: int,
) -> LockDecision:
    now = _now()
    expires_at = _iso(now + dt.timedelta(seconds=ttl_seconds))
    now_iso = _iso(now)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT holder_email, expires_at FROM advisory_locks"
            " WHERE resource_type=? AND resource_id=?",
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
            return LockDecision(True, holder, expires_at)
        current_holder = row["holder_email"]
        current_expires = row["expires_at"]
        if current_holder == holder or _parse_iso(current_expires) <= now:
            conn.execute(
                "UPDATE advisory_locks"
                " SET holder_email=?, expires_at=?, updated_at=?"
                " WHERE resource_type=? AND resource_id=?",
                (holder, expires_at, now_iso, resource_type, resource_id),
            )
            return LockDecision(True, holder, expires_at)
        return LockDecision(False, current_holder, current_expires)


def get_lock(resource_type: str, resource_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT resource_type, resource_id, holder_email, expires_at,"
            " created_at, updated_at FROM advisory_locks"
            " WHERE resource_type=? AND resource_id=?",
            (resource_type, resource_id),
        ).fetchone()
    return dict(row) if row else None


def release_lock(resource_type: str, resource_id: str, holder: str) -> bool:
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM advisory_locks"
            " WHERE resource_type=? AND resource_id=? AND holder_email=?",
            (resource_type, resource_id, holder),
        )
        return cur.rowcount == 1


def expire_locks(now: dt.datetime | None = None) -> int:
    cutoff = _iso(now or _now())
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM advisory_locks WHERE expires_at <= ?",
            (cutoff,),
        )
        return cur.rowcount
