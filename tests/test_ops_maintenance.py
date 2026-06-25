"""Tests for operational retention / VACUUM maintenance (TASK-084)."""

from __future__ import annotations

import datetime as dt

from marcedit_web.lib import db
from marcedit_web.ops import maintenance


_NOW = dt.datetime(2026, 6, 25, 12, 0, 0, tzinfo=dt.timezone.utc)


def _insert_audit(ts: str, kind: str = "upload-accepted") -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO audit_events(ts, user_email, kind, payload_json)"
            " VALUES (?, ?, ?, ?)",
            (ts, "alice@example.edu", kind, "{}"),
        )


def test_prune_audit_events_deletes_rows_older_than_retention():
    """Rows before the retention cutoff should be deleted; newer rows stay."""
    db.init_schema()
    _insert_audit("2026-03-01T00:00:00Z", "old")
    _insert_audit("2026-06-20T00:00:00Z", "new")

    deleted = maintenance.prune_audit_events(retain_days=30, now=_NOW)

    assert deleted == 1
    with db.connect() as conn:
        kinds = [row["kind"] for row in conn.execute("SELECT kind FROM audit_events")]
    assert kinds == ["new"]


def test_prune_audit_jsonl_deletes_old_named_logs(tmp_path):
    """Audit JSONL retention should follow audit-YYYY-MM-DD.log filenames."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    old = audit_dir / "audit-2026-03-01.log"
    new = audit_dir / "audit-2026-06-20.log"
    unrelated = audit_dir / "notes.txt"
    old.write_text("{}\n")
    new.write_text("{}\n")
    unrelated.write_text("keep\n")

    deleted = maintenance.prune_audit_jsonl(audit_dir, retain_days=30, now=_NOW)

    assert deleted == 1
    assert not old.exists()
    assert new.exists()
    assert unrelated.exists()


def test_run_retention_vacuums_and_reports_counts(tmp_path, monkeypatch):
    """The public maintenance entrypoint should prune both audit surfaces."""
    db.init_schema()
    _insert_audit("2026-03-01T00:00:00Z")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "audit-2026-03-01.log").write_text("{}\n")
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(audit_dir))

    result = maintenance.run_retention(retain_days=30, now=_NOW, vacuum=True)

    assert result.sql_rows_deleted == 1
    assert result.jsonl_files_deleted == 1
    assert result.vacuum_ran is True


def test_main_prints_retention_summary(tmp_path, monkeypatch, capsys):
    """Operators need a schedulable CLI with clear one-line output."""
    db.init_schema()
    _insert_audit("2026-03-01T00:00:00Z")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(audit_dir))

    exit_code = maintenance.main([
        "retention",
        "--retain-days",
        "30",
        "--now",
        "2026-06-25T12:00:00Z",
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "sql_rows_deleted=1" in captured.out
    assert "jsonl_files_deleted=0" in captured.out
    assert "vacuum_ran=True" in captured.out
