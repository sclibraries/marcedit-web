"""Tests for the operational readiness probe (TASK-084)."""

from __future__ import annotations

import sqlite3

from marcedit_web.lib import db
from marcedit_web.ops import health


def test_check_readiness_initializes_and_writes_db(tmp_path, monkeypatch):
    """Readiness must prove the catalog DB is reachable and writable."""
    db_path = tmp_path / "ready.db"
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(db_path))
    db.reset_for_tests()

    result = health.check_readiness()

    assert result.ok is True
    assert result.message == "ok"
    assert db_path.exists()
    with db.connect() as conn:
        row = conn.execute("SELECT version FROM _schema_version").fetchone()
    assert row["version"] == db.SCHEMA_VERSION


def test_check_readiness_fails_when_db_path_is_directory(tmp_path, monkeypatch):
    """A bad DB path should fail readiness with a cataloger-safe message."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path))
    db.reset_for_tests()

    result = health.check_readiness()

    assert result.ok is False
    assert "unable to open database file" in result.message.lower()


def test_main_returns_zero_for_ready_db(tmp_path, monkeypatch, capsys):
    """The CLI form is what Docker/systemd call."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "ready.db"))
    db.reset_for_tests()

    exit_code = health.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "ok"


def test_write_probe_rolls_back_without_leaving_probe_table(tmp_path, monkeypatch):
    """The write probe should test writability without changing schema."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "ready.db"))
    db.reset_for_tests()

    result = health.check_readiness()

    assert result.ok is True
    with sqlite3.connect(db.db_path()) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "_marcedit_health_probe" not in names
