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
