from __future__ import annotations

import json

from marcedit_web.lib import db, jobs, snapshot_actions


def test_record_job_snapshot_skips_anonymous_user(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()

    result = snapshot_actions.record_job_snapshot(
        job_id=1,
        user_email="anonymous",
        kind="task-run",
        label="Normalize",
        before_bytes=b"before",
        after_bytes=b"after",
    )

    assert result is None


def test_record_job_snapshot_persists_signed_in_job_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("cataloger@example.edu", "Batch cleanup")

    row = snapshot_actions.record_job_snapshot(
        job_id=job["id"],
        user_email="cataloger@example.edu",
        kind="task-run",
        label="Normalize fields",
        before_bytes=b"before",
        after_bytes=b"after",
        summary={"changed_count": 2},
    )

    assert row is not None
    assert row["job_id"] == job["id"]
    assert row["user_email"] == "cataloger@example.edu"
    assert json.loads(row["summary_json"])["changed_count"] == 2


def test_record_edit_snapshot_marks_record_and_source(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("cataloger@example.edu", "Record edits")

    row = snapshot_actions.record_edit_snapshot(
        job_id=job["id"],
        user_email="cataloger@example.edu",
        label="Single record edit",
        before_bytes=b"before",
        after_bytes=b"after",
        record_index=3,
        source="view-edit",
    )

    assert row is not None
    assert row["kind"] == "edit"
    summary = json.loads(row["summary_json"])
    assert summary["record_index"] == 3
    assert summary["source"] == "view-edit"
