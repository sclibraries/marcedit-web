"""Tests for marcedit_web.lib.audit (append-only JSONL audit log)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from marcedit_web.lib import audit


def _read_lines(p: Path) -> list[dict]:
    text = p.read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_audit_event_writes_one_jsonl_line(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    audit.audit_event("upload-accepted", user="eppn@example", size=12345)

    files = list(tmp_path.glob("audit-*.log"))
    assert len(files) == 1
    rows = _read_lines(files[0])
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "upload-accepted"
    assert row["user"] == "eppn@example"
    assert row["size"] == 12345
    assert "ts" in row and row["ts"].endswith("Z")


def test_audit_event_appends_multiple_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    audit.audit_event("upload-accepted", user="a", size=1)
    audit.audit_event("upload-rejected", user="b", reason="upload")
    audit.audit_event("task-saved", user="c", task_name="t")

    files = list(tmp_path.glob("audit-*.log"))
    rows = _read_lines(files[0])
    assert [r["kind"] for r in rows] == [
        "upload-accepted", "upload-rejected", "task-saved",
    ]


def test_audit_event_default_user_is_anonymous(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    audit.audit_event("upload-accepted")
    files = list(tmp_path.glob("audit-*.log"))
    assert _read_lines(files[0])[0]["user"] == "anonymous"


def test_audit_event_survives_concurrent_writes(tmp_path, monkeypatch):
    """20 threads × 5 events each: every line must be a complete JSON object.

    With no lock the line-level append would interleave under contention
    and parsers would see truncated rows. The module-level threading
    lock prevents that — this test would fail (random JSONDecodeError)
    if the lock were removed.
    """
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))

    def writer(tid: int):
        for i in range(5):
            audit.audit_event(
                "concurrent-test",
                user=f"thread-{tid}",
                idx=i,
                payload="x" * 200,
            )

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    files = list(tmp_path.glob("audit-*.log"))
    rows = _read_lines(files[0])
    assert len(rows) == 100  # 20 × 5
    assert all(r["kind"] == "concurrent-test" for r in rows)


def test_audit_event_swallows_io_errors(monkeypatch, caplog):
    """A write failure logs a warning but never raises into the caller."""
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", "/does/not/exist/and/cannot/be/created")

    # Force mkdir to fail by patching the resolved path's mkdir.
    original_audit_dir = audit._audit_dir

    def broken_audit_dir():
        raise OSError("permission denied for audit dir")

    monkeypatch.setattr(audit, "_audit_dir", broken_audit_dir)

    # Must not raise.
    with caplog.at_level("WARNING", logger="marcedit_web.audit"):
        audit.audit_event("any-event", user="x")
    # Restore (not strictly needed for monkeypatch but keep tidy).
    monkeypatch.setattr(audit, "_audit_dir", original_audit_dir)
    assert any("audit-write failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# TASK-049 — SQL mirror of audit events
# ---------------------------------------------------------------------------

from marcedit_web.lib import db  # noqa: E402 — kept near the SQL-mirror tests


def test_audit_event_writes_sql_row(tmp_path, monkeypatch):
    """Each audit_event call must produce one matching SQL row."""
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    audit.audit_event("upload-accepted", user="alice@example.edu", size=2048)

    with db.connect() as conn:
        rows = list(conn.execute(
            "SELECT ts, user_email, kind, payload_json FROM audit_events"
        ))
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "upload-accepted"
    assert row["user_email"] == "alice@example.edu"
    assert row["ts"].endswith("Z")
    payload = json.loads(row["payload_json"])
    # ts/kind/user live in indexed columns; payload_json carries
    # only the event-specific extras.
    assert payload == {"size": 2048}


def test_audit_event_sql_and_jsonl_stay_in_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    audit.audit_event("upload-accepted", user="a", size=1)
    audit.audit_event("task-saved", user="b", task_name="t")
    audit.audit_event("conversion-issued", user="c", kind_label="utf8")

    jsonl_rows = _read_lines(list(tmp_path.glob("audit-*.log"))[0])
    with db.connect() as conn:
        sql_rows = list(conn.execute(
            "SELECT ts, user_email, kind FROM audit_events ORDER BY id"
        ))

    assert len(jsonl_rows) == len(sql_rows) == 3
    for j, s in zip(jsonl_rows, sql_rows):
        assert j["ts"] == s["ts"]
        assert j["kind"] == s["kind"]
        assert j["user"] == s["user_email"]


def test_audit_event_sql_failure_does_not_block_jsonl(tmp_path, monkeypatch, caplog):
    """If the DB is broken, the JSONL line still lands and the action returns."""
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    # Point at an impossible DB path — parent is a regular file, so
    # mkdir(parents=True) fails and connect() raises.
    bad_file = tmp_path / "not-a-dir.txt"
    bad_file.write_text("x")
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(bad_file / "child.db"))
    db.reset_for_tests()

    with caplog.at_level("WARNING", logger="marcedit_web.audit"):
        audit.audit_event("upload-accepted", user="x", size=1)

    jsonl_rows = _read_lines(list(tmp_path.glob("audit-*.log"))[0])
    assert len(jsonl_rows) == 1
    assert any(
        "audit-sql-write failed" in r.message for r in caplog.records
    )
