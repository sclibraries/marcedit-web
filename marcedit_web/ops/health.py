"""Readiness probe for marcedit-web private service operation."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass

from marcedit_web.lib import db


@dataclass(frozen=True)
class ReadinessResult:
    ok: bool
    message: str


def check_readiness() -> ReadinessResult:
    """Verify SQLite schema exists and the DB accepts a write transaction."""
    try:
        db.init_schema()
        _probe_writable_db()
    except sqlite3.Error as exc:
        return ReadinessResult(False, str(exc))
    except OSError as exc:
        return ReadinessResult(False, str(exc))
    return ReadinessResult(True, "ok")


def _probe_writable_db() -> None:
    """Open a rollbacked write transaction against the main DB file.

    A temp-table write would only prove the temp database is writable. This
    creates and inserts into a main-schema probe table inside an explicit
    transaction, then rolls back so the healthcheck leaves no schema/data behind.
    """
    path = db.db_path()
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS _marcedit_health_probe (id INTEGER)")
        conn.execute("INSERT INTO _marcedit_health_probe(id) VALUES (1)")
        conn.execute("ROLLBACK")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check marcedit-web private service readiness.",
    )
    parser.parse_args(argv)

    result = check_readiness()
    stream = sys.stdout if result.ok else sys.stderr
    print(result.message, file=stream)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
