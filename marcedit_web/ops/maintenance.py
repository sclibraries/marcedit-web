"""Operational retention and VACUUM commands."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from marcedit_web.lib import db


@dataclass(frozen=True)
class RetentionResult:
    sql_rows_deleted: int
    jsonl_files_deleted: int
    vacuum_ran: bool


def run_retention(
    *,
    retain_days: int,
    now: dt.datetime | None = None,
    vacuum: bool = True,
) -> RetentionResult:
    """Prune audit surfaces and optionally VACUUM the SQLite DB."""
    if retain_days < 1:
        raise ValueError("retain_days must be at least 1")
    now = _utc(now)
    db.init_schema()
    sql_deleted = prune_audit_events(retain_days=retain_days, now=now)
    jsonl_deleted = prune_audit_jsonl(_audit_dir(), retain_days=retain_days, now=now)
    if vacuum:
        vacuum_db()
    return RetentionResult(
        sql_rows_deleted=sql_deleted,
        jsonl_files_deleted=jsonl_deleted,
        vacuum_ran=vacuum,
    )


def prune_audit_events(*, retain_days: int, now: dt.datetime | None = None) -> int:
    """Delete SQL audit rows older than ``retain_days``."""
    cutoff = _cutoff_iso(retain_days, _utc(now))
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM audit_events WHERE ts < ?", (cutoff,))
        return int(cur.rowcount or 0)


def prune_audit_jsonl(
    audit_dir: Path,
    *,
    retain_days: int,
    now: dt.datetime | None = None,
) -> int:
    """Delete old ``audit-YYYY-MM-DD.log`` files by date in the filename."""
    if not audit_dir.exists():
        return 0
    cutoff_date = (_utc(now) - dt.timedelta(days=retain_days)).date()
    deleted = 0
    for path in audit_dir.iterdir():
        audit_date = _audit_log_date(path)
        if audit_date is None or audit_date >= cutoff_date:
            continue
        path.unlink()
        deleted += 1
    return deleted


def vacuum_db() -> None:
    """Checkpoint WAL and VACUUM in autocommit mode."""
    path = db.db_path()
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run marcedit-web operational maintenance.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    retention = sub.add_parser("retention", help="prune audit history and VACUUM")
    retention.add_argument("--retain-days", type=int, default=90)
    retention.add_argument("--now", help="UTC timestamp override for tests")
    retention.add_argument(
        "--no-vacuum",
        action="store_true",
        help="prune without running SQLite VACUUM",
    )
    args = parser.parse_args(argv)

    if args.command == "retention":
        try:
            now = _parse_now(args.now) if args.now else None
            result = run_retention(
                retain_days=args.retain_days,
                now=now,
                vacuum=not args.no_vacuum,
            )
        except Exception as exc:  # noqa: BLE001 - CLI must fail loud
            print(f"retention failed: {exc}", file=sys.stderr)
            return 1
        print(
            "retention complete: "
            f"sql_rows_deleted={result.sql_rows_deleted} "
            f"jsonl_files_deleted={result.jsonl_files_deleted} "
            f"vacuum_ran={result.vacuum_ran}"
        )
        return 0
    return 1


def _audit_dir() -> Path:
    return Path(os.environ.get("MARCEDIT_WEB_AUDIT_DIR", "data/audit"))


def _cutoff_iso(retain_days: int, now: dt.datetime) -> str:
    cutoff = now - dt.timedelta(days=retain_days)
    return cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit_log_date(path: Path) -> dt.date | None:
    name = path.name
    if not (name.startswith("audit-") and name.endswith(".log")):
        return None
    raw = name[len("audit-"):-len(".log")]
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_now(raw: str) -> dt.datetime:
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    return _utc(dt.datetime.fromisoformat(normalized))


def _utc(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
