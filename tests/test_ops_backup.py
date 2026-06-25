"""Tests for operational backup / restore (TASK-084)."""

from __future__ import annotations

import sqlite3

from marcedit_web.lib import db
from marcedit_web.ops import backup


def _insert_audit(kind: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO audit_events(ts, user_email, kind, payload_json)"
            " VALUES (?, ?, ?, ?)",
            ("2026-06-25T12:00:00Z", "alice@example.edu", kind, "{}"),
        )


def test_create_backup_copies_db_and_audit_jsonl(tmp_path, monkeypatch):
    """A backup should contain a restorable SQLite DB and audit JSONL files."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "live.db"))
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(audit_dir))
    db.reset_for_tests()
    db.init_schema()
    _insert_audit("upload-accepted")
    (audit_dir / "audit-2026-06-25.log").write_text('{"kind":"upload-accepted"}\n')

    result = backup.create_backup(tmp_path / "backup")

    assert result.db_backup_path.exists()
    assert (result.backup_dir / "audit" / "audit-2026-06-25.log").exists()
    with sqlite3.connect(result.db_backup_path) as conn:
        row = conn.execute("SELECT kind FROM audit_events").fetchone()
    assert row[0] == "upload-accepted"


def test_restore_backup_replaces_db_and_audit_jsonl(tmp_path, monkeypatch):
    """Restoring a backup should yield a working DB with backed-up rows."""
    live_db = tmp_path / "live.db"
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(live_db))
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(audit_dir))
    db.reset_for_tests()
    db.init_schema()
    _insert_audit("before-backup")
    (audit_dir / "audit-2026-06-25.log").write_text('{"kind":"before-backup"}\n')
    backup_dir = backup.create_backup(tmp_path / "backup").backup_dir

    # Mutate live state after backup so restore has something to replace.
    _insert_audit("after-backup")
    (audit_dir / "audit-2026-06-26.log").write_text('{"kind":"after-backup"}\n')

    restored = backup.restore_backup(backup_dir)

    assert restored.db_path == live_db
    with db.connect() as conn:
        kinds = [row["kind"] for row in conn.execute("SELECT kind FROM audit_events")]
    assert kinds == ["before-backup"]
    assert (audit_dir / "audit-2026-06-25.log").exists()
    assert not (audit_dir / "audit-2026-06-26.log").exists()


def test_backup_main_prints_created_paths(tmp_path, monkeypatch, capsys):
    """The backup CLI should be usable from cron/manual operator workflows."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "live.db"))
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path / "audit"))
    db.reset_for_tests()
    db.init_schema()

    exit_code = backup.main(["create", str(tmp_path / "backup")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "backup created:" in captured.out
    assert "marcedit.db" in captured.out


def test_restore_main_restores_backup(tmp_path, monkeypatch, capsys):
    """The restore CLI should run the same restore code path as tests."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "live.db"))
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path / "audit"))
    db.reset_for_tests()
    db.init_schema()
    _insert_audit("before-backup")
    backup_dir = backup.create_backup(tmp_path / "backup").backup_dir

    exit_code = backup.main(["restore", str(backup_dir)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "backup restored:" in captured.out
