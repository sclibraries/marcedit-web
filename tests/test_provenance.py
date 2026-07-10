"""Tests for persisted undo/provenance snapshots (TASK-082)."""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import db, jobs, provenance


def test_create_snapshot_persists_before_after_and_user(tmp_path, monkeypatch):
    """Snapshots should survive session loss as DB rows plus MRC files."""
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("alice@example.edu", "Vendor load")

    snap = provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="task-run",
        label="normalize URLs",
        before_bytes=b"before-mrc",
        after_bytes=b"after-mrc",
        summary={"changed": 2},
    )

    assert Path(snap["before_path"]).read_bytes() == b"before-mrc"
    assert Path(snap["after_path"]).read_bytes() == b"after-mrc"
    assert snap["user_email"] == "alice@example.edu"
    assert snap["kind"] == "task-run"
    assert snap["summary_json"] == '{"changed": 2}'


def test_create_snapshot_copies_paths_without_materializing_them(
    tmp_path, monkeypatch
):
    """Snapshot retention is disk-to-disk even for a full 100K batch."""
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("alice@example.edu", "Vendor load")
    before = tmp_path / "before.mrc"
    after = tmp_path / "after.mrc"
    before.write_bytes(b"before-mrc")
    after.write_bytes(b"after-mrc")

    def _read_bytes(self):
        raise AssertionError("snapshot creation must not read a whole MRC")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)

    snap = provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="task-run",
        label="normalize URLs",
        before_path=before,
        after_path=after,
    )

    with Path(snap["before_path"]).open("rb") as fh:
        assert fh.read() == b"before-mrc"
    with Path(snap["after_path"]).open("rb") as fh:
        assert fh.read() == b"after-mrc"


def test_create_snapshot_cleans_partial_files_when_copy_fails(
    tmp_path, monkeypatch
):
    """A failed snapshot must not consume retention space with orphan files."""
    root = tmp_path / "snapshots"
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(root))
    db.init_schema()
    job = jobs.create_job("alice@example.edu", "Vendor load")
    before = tmp_path / "before.mrc"
    before.write_bytes(b"before-mrc")

    with pytest.raises(FileNotFoundError):
        provenance.create_snapshot(
            job_id=job["id"],
            user_email="alice@example.edu",
            kind="task-run",
            label="normalize URLs",
            before_path=before,
            after_path=tmp_path / "missing-after.mrc",
        )

    assert list(root.rglob("*.mrc")) == []


def test_list_snapshots_returns_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("alice@example.edu", "Vendor load")
    first = provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="edit",
        label="first",
        before_bytes=b"before-1",
        after_bytes=b"after-1",
    )
    second = provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="edit",
        label="second",
        before_bytes=b"before-2",
        after_bytes=b"after-2",
    )

    rows = provenance.list_snapshots(job["id"])

    assert [row["id"] for row in rows] == [second["id"], first["id"]]


def test_restore_snapshot_returns_pre_change_bytes(tmp_path, monkeypatch):
    """One-click rollback uses the stored pre-change MRC bytes."""
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("alice@example.edu", "Vendor load")
    snap = provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="task-run",
        label="normalize URLs",
        before_bytes=b"rollback-target",
        after_bytes=b"changed-state",
    )

    assert provenance.restore_bytes(snap["id"]) == b"rollback-target"


def test_restore_snapshot_exposes_pre_change_path(tmp_path, monkeypatch):
    """Rollback can reattach/copy the snapshot without reading it into RAM."""
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("alice@example.edu", "Vendor load")
    snap = provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="task-run",
        label="normalize URLs",
        before_bytes=b"rollback-target",
        after_bytes=b"changed-state",
    )

    assert provenance.restore_path(snap["id"]) == Path(snap["before_path"])


def test_snapshot_cap_prunes_oldest_files_and_rows(tmp_path, monkeypatch):
    """Snapshot storage should stay bounded per job."""
    monkeypatch.setenv("MARCEDIT_WEB_SNAPSHOTS_ROOT", str(tmp_path / "snapshots"))
    db.init_schema()
    job = jobs.create_job("alice@example.edu", "Vendor load")
    first = provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="edit",
        label="first",
        before_bytes=b"before-1",
        after_bytes=b"after-1",
        cap=2,
    )
    provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="edit",
        label="second",
        before_bytes=b"before-2",
        after_bytes=b"after-2",
        cap=2,
    )
    provenance.create_snapshot(
        job_id=job["id"],
        user_email="alice@example.edu",
        kind="edit",
        label="third",
        before_bytes=b"before-3",
        after_bytes=b"after-3",
        cap=2,
    )

    rows = provenance.list_snapshots(job["id"])

    assert [row["label"] for row in rows] == ["third", "second"]
    assert not Path(first["before_path"]).exists()
    assert not Path(first["after_path"]).exists()
