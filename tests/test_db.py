"""Tests for marcedit_web.lib.db (TASK-049 — SQLite foundation).

DB isolation per test is provided by the autouse ``_isolated_sqlite``
fixture in conftest.py — it sets ``MARCEDIT_WEB_DB_PATH`` to a
tmp_path-scoped file and clears the init flag.
"""

from __future__ import annotations

import sqlite3

import pytest

from marcedit_web.lib import db


def test_db_path_default(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_DB_PATH", raising=False)
    assert str(db.db_path()) == "data/marcedit.db"


def test_db_path_env_override(monkeypatch, tmp_path):
    target = tmp_path / "alt.db"
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(target))
    assert db.db_path() == target


def test_connect_commits_on_normal_exit():
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO audit_events(ts, user_email, kind, payload_json)"
            " VALUES (?, ?, ?, ?)",
            ("2026-05-27T00:00:00Z", "alice@example.edu", "test", "{}"),
        )
    # Reopen a separate connection — if the prior block's commit
    # didn't fire, this row wouldn't be visible.
    with db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()
    assert row["n"] == 1


def test_connect_rolls_back_on_exception():
    db.init_schema()
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO audit_events(ts, user_email, kind, payload_json)"
                " VALUES (?, ?, ?, ?)",
                ("2026-05-27T00:00:00Z", "alice@example.edu", "test", "{}"),
            )
            raise RuntimeError("force rollback")
    with db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()
    assert row["n"] == 0


def test_init_schema_idempotent():
    db.init_schema()
    # Second call must not raise.
    db.reset_for_tests()
    db.init_schema()
    with db.connect() as conn:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"audit_events", "_schema_version"}.issubset(names)


def test_init_schema_sets_version():
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute("SELECT version FROM _schema_version").fetchone()
    assert row["version"] == db.SCHEMA_VERSION


def test_init_schema_creates_indexes():
    db.init_schema()
    with db.connect() as conn:
        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
    assert {"idx_audit_user_ts", "idx_audit_kind_ts"}.issubset(idx)


def test_foreign_keys_enabled():
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
    # SQLite returns 0/1 for the pragma.
    assert row[0] == 1


def test_connect_row_factory_is_dict_like():
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO audit_events(ts, user_email, kind, payload_json)"
            " VALUES (?, ?, ?, ?)",
            ("2026-05-27T00:00:00Z", "alice@example.edu", "upload", "{}"),
        )
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ts, user_email, kind FROM audit_events LIMIT 1"
        ).fetchone()
    # Column-by-name access requires sqlite3.Row.
    assert row["user_email"] == "alice@example.edu"
    assert row["kind"] == "upload"


def test_wal_journal_mode_enabled_after_init():
    db.init_schema()
    with db.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_connect_creates_parent_dir(monkeypatch, tmp_path):
    nested = tmp_path / "nested" / "deeper" / "db.sqlite"
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(nested))
    db.reset_for_tests()
    db.init_schema()
    assert nested.exists()
