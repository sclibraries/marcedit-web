from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from marcedit_web.lib import db, jobs, snapshot_actions


def test_staged_store_path_is_disk_backed_and_cleaned():
    """Mutation flows retain a temporary pre-state path, never batch bytes."""
    writes = []

    def _write(path):
        writes.append(Path(path))
        Path(path).write_bytes(b"logical-store")
        return len(b"logical-store")

    store = SimpleNamespace(write_mrc_to=_write)

    with snapshot_actions.staged_store_path(store) as staged:
        assert staged.read_bytes() == b"logical-store"
        assert writes == [staged]

    assert not staged.exists()
    assert not staged.parent.exists()


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


def test_restore_version_adopts_selected_bytes_as_new_child(monkeypatch, tmp_path):
    """Restore copies history forward; it never rewinds the current pointer."""
    from marcedit_web.render import history

    selected = tmp_path / "v1.mrc"
    selected.write_bytes(b"historical-version")
    calls = []
    monkeypatch.setattr(history.st, "session_state", {"job_file_id": 9})
    monkeypatch.setattr(history.session, "current_user_id", lambda: "cat@example.edu")
    monkeypatch.setattr(
        history.job_files,
        "get_version",
        lambda version_id, user: {
            "id": version_id,
            "job_file_id": 9,
            "version_number": 1,
            "file_path": str(selected),
        },
    )
    monkeypatch.setattr(
        history.session,
        "adopt_current_candidate",
        lambda **kwargs: calls.append({
            **kwargs,
            "candidate_bytes": Path(kwargs["candidate_path"]).read_bytes(),
        }) or {"version_number": 4},
    )

    created = history._restore_version(12)

    assert created["version_number"] == 4
    assert calls[0]["source_kind"] == "restore"
    assert calls[0]["label"] == "Restore version 1"
    assert calls[0]["summary"] == {"restored_version_id": 12}
    assert calls[0]["candidate_bytes"] == b"historical-version"
