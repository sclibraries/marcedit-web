"""Durable per-file work item tests for TASK-151."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from marcedit_web.lib import collaboration, db, job_files, jobs


@pytest.fixture(autouse=True)
def _isolated_job_files_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))


def attach_fixture(job_id: int, tmp_path: Path, filename: str, data: bytes):
    source = tmp_path / f"incoming-{filename}"
    source.write_bytes(data)
    return job_files.attach_file(
        job_id=job_id,
        user_email="owner@example.edu",
        source_path=source,
        filename=filename,
        record_count=1,
        file_bytes=len(data),
    )


def test_attach_file_copies_original_and_creates_version_one(tmp_path):
    source = tmp_path / "incoming.mrc"
    source.write_bytes(b"first")
    job = jobs.create_job("owner@example.edu", "Routledge")

    attached = job_files.attach_file(
        job_id=job["id"],
        user_email="owner@example.edu",
        source_path=source,
        filename="deletes.mrc",
        record_count=1,
        file_bytes=5,
    )
    source.write_bytes(b"changed")

    current = job_files.get_current_version(attached["id"], "owner@example.edu")
    assert current["version_number"] == 1
    assert current["source_kind"] == "original"
    assert Path(current["file_path"]).read_bytes() == b"first"
    assert attached["status"] == "new"


def test_two_attachments_in_one_job_have_separate_current_versions(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    first = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    second = attach_fixture(job["id"], tmp_path, "fresh.mrc", b"two")

    rows = job_files.list_files(job["id"], "owner@example.edu")
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert {row["current_version_number"] for row in rows} == {1}
    assert first["current_version_id"] != second["current_version_id"]


def test_attachment_rejects_incorrect_file_size(tmp_path):
    source = tmp_path / "incoming.mrc"
    source.write_bytes(b"first")
    job = jobs.create_job("owner@example.edu", "Routledge")

    with pytest.raises(job_files.JobFileError, match="file size does not match"):
        job_files.attach_file(
            job_id=job["id"],
            user_email="owner@example.edu",
            source_path=source,
            filename="deletes.mrc",
            record_count=1,
            file_bytes=4,
        )


def _fail_attachment_commit(monkeypatch, *, persist_before_raise: bool) -> None:
    original_connect = db.connect
    call_count = 0

    @contextmanager
    def failing_connect():
        nonlocal call_count
        call_count += 1
        if call_count != 2:  # first call is the public API's role check
            with original_connect() as conn:
                yield conn
            return
        conn = sqlite3.connect(db.db_path(), isolation_level="DEFERRED")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            if persist_before_raise:
                conn.commit()
                raise RuntimeError("commit persisted but confirmation failed")
            raise RuntimeError("commit failed before persistence")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(db, "connect", failing_connect)


def test_attachment_commit_failure_before_persistence_cleans_original(
    tmp_path, monkeypatch,
):
    """A rolled-back attachment must leave no immutable orphan or SQL row."""
    source = tmp_path / "incoming.mrc"
    source.write_bytes(b"first")
    job = jobs.create_job("owner@example.edu", "Routledge")
    _fail_attachment_commit(monkeypatch, persist_before_raise=False)

    with pytest.raises(RuntimeError, match="failed before persistence"):
        job_files.attach_file(
            job_id=job["id"],
            user_email="owner@example.edu",
            source_path=source,
            filename="deletes.mrc",
            record_count=1,
            file_bytes=5,
        )

    assert job_files.list_files(job["id"], "owner@example.edu") == []
    assert list(job_files.versions_root().glob("*/versions/*.mrc")) == []


def test_attachment_persisted_then_raised_retains_referenced_original(
    tmp_path, monkeypatch,
):
    """Uncertain commit confirmation must never unlink referenced version 1."""
    source = tmp_path / "incoming.mrc"
    source.write_bytes(b"first")
    job = jobs.create_job("owner@example.edu", "Routledge")
    _fail_attachment_commit(monkeypatch, persist_before_raise=True)

    with pytest.raises(job_files.JobFileError, match="confirmation failed"):
        job_files.attach_file(
            job_id=job["id"],
            user_email="owner@example.edu",
            source_path=source,
            filename="deletes.mrc",
            record_count=1,
            file_bytes=5,
        )

    rows = job_files.list_files(job["id"], "owner@example.edu")
    assert len(rows) == 1
    current = job_files.get_current_version(rows[0]["id"], "owner@example.edu")
    assert Path(current["file_path"]).read_bytes() == b"first"


def test_attachment_removes_partial_candidate_when_copy_fails(tmp_path, monkeypatch):
    source = tmp_path / "incoming.mrc"
    source.write_bytes(b"first")
    job = jobs.create_job("owner@example.edu", "Routledge")

    def fail_after_destination_creation(source_path, candidate):
        candidate.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(job_files.shutil, "copyfile", fail_after_destination_creation)

    with pytest.raises(OSError, match="disk full"):
        job_files.attach_file(
            job_id=job["id"],
            user_email="owner@example.edu",
            source_path=source,
            filename="deletes.mrc",
            record_count=1,
            file_bytes=5,
        )

    assert list((job_files.versions_root() / "pending").iterdir()) == []
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM job_files").fetchone()[0] == 0


def test_read_apis_require_job_access(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    current = job_files.get_current_version(attached["id"], "owner@example.edu")

    with pytest.raises(job_files.JobFileError, match="job file not found"):
        job_files.get_file(attached["id"], "outsider@example.edu")
    with pytest.raises(job_files.JobFileError, match="job file version not found"):
        job_files.get_version(current["id"], "outsider@example.edu")


def test_list_files_hides_archived_files_by_default(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_files SET archived_by=?, archived_at=? WHERE id=?",
            ("owner@example.edu", "2026-07-14T12:00:00Z", attached["id"]),
        )

    assert job_files.list_files(job["id"], "owner@example.edu") == []
    assert [row["id"] for row in job_files.list_files(
        job["id"], "owner@example.edu", include_archived=True
    )] == [attached["id"]]


def test_archive_file_preserves_versions_releases_checkout_and_records_activity(
    tmp_path,
):
    """Normal removal must retain the work product and release its checkout."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    version = job_files.get_current_version(attached["id"], "owner@example.edu")
    version_path = Path(version["file_path"])
    export_path = tmp_path / "export.mrc"
    export_path.write_bytes(b"export")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")
    with db.connect() as conn:
        export_id = conn.execute(
            "INSERT INTO job_file_exports(job_file_id,version_id,purpose,description,"
            "filename,file_path,record_count,validation_json,state,created_by,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (
                attached["id"],
                version["id"],
                "EDS deletion load",
                "",
                "export.mrc",
                str(export_path),
                1,
                "{}",
                "draft",
                "owner@example.edu",
                "2026-07-14T12:00:00Z",
            ),
        ).fetchone()["id"]

    archived = job_files.archive_file(
        attached["id"],
        by="owner@example.edu",
        opened_version_id=version["id"],
    )

    assert archived["archived_by"] == "owner@example.edu"
    assert archived["archived_at"] is not None
    assert version_path.read_bytes() == b"one"
    assert export_path.read_bytes() == b"export"
    assert job_files.get_file(
        attached["id"], "owner@example.edu"
    )["current_version_id"] == version["id"]
    assert job_files.get_version(
        version["id"], "owner@example.edu"
    )["file_path"] == str(version_path)
    with db.connect() as conn:
        assert conn.execute(
            "SELECT file_path FROM job_file_exports WHERE id=?", (export_id,)
        ).fetchone()["file_path"] == str(export_path)
        assert conn.execute(
            "SELECT 1 FROM advisory_locks WHERE resource_type='job-file'"
            " AND resource_id=?",
            (str(attached["id"]),),
        ).fetchone() is None
        activity = conn.execute(
            "SELECT kind,job_file_id FROM job_activity ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert dict(activity) == {
        "kind": "job-file-archived",
        "job_file_id": attached["id"],
    }


def test_archive_rejects_non_holder_without_changing_file_or_lock(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    jobs.grant_access(
        job["id"], "editor@example.edu", "editor", by="owner@example.edu"
    )
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")

    with pytest.raises(job_files.JobFileError, match="checkout"):
        job_files.archive_file(
            attached["id"],
            by="editor@example.edu",
            opened_version_id=attached["current_version_id"],
        )

    row = job_files.get_file(attached["id"], "owner@example.edu")
    assert row["archived_at"] is None
    with db.connect() as conn:
        lock = conn.execute(
            "SELECT holder_email FROM advisory_locks"
            " WHERE resource_type='job-file' AND resource_id=?",
            (str(attached["id"]),),
        ).fetchone()
        activity_count = conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE kind='job-file-archived'"
        ).fetchone()[0]
    assert lock["holder_email"] == "owner@example.edu"
    assert activity_count == 0


def test_archive_rejects_stale_version_without_changing_file_or_lock(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")

    with pytest.raises(job_files.JobFileError, match="changed"):
        job_files.archive_file(
            attached["id"],
            by="owner@example.edu",
            opened_version_id=int(attached["current_version_id"]) + 1,
        )

    row = job_files.get_file(attached["id"], "owner@example.edu")
    assert row["archived_at"] is None
    with db.connect() as conn:
        lock = conn.execute(
            "SELECT holder_email FROM advisory_locks"
            " WHERE resource_type='job-file' AND resource_id=?",
            (str(attached["id"]),),
        ).fetchone()
        activity_count = conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE kind='job-file-archived'"
        ).fetchone()[0]
    assert lock["holder_email"] == "owner@example.edu"
    assert activity_count == 0


def test_archive_rejects_expired_checkout_without_changing_file_or_lock(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(
        attached["id"], "owner@example.edu", ttl_seconds=-1
    )
    before = job_files.get_file(attached["id"], "owner@example.edu")
    with db.connect() as conn:
        lock_before = dict(conn.execute(
            "SELECT * FROM advisory_locks WHERE resource_type='job-file'"
            " AND resource_id=?",
            (str(attached["id"]),),
        ).fetchone())

    with pytest.raises(job_files.JobFileError, match="checkout"):
        job_files.archive_file(
            attached["id"],
            by="owner@example.edu",
            opened_version_id=attached["current_version_id"],
        )

    after = job_files.get_file(attached["id"], "owner@example.edu")
    assert after["archived_at"] == before["archived_at"]
    assert after["archived_by"] == before["archived_by"]
    assert after["current_version_id"] == before["current_version_id"]
    with db.connect() as conn:
        lock_after = dict(conn.execute(
            "SELECT * FROM advisory_locks WHERE resource_type='job-file'"
            " AND resource_id=?",
            (str(attached["id"]),),
        ).fetchone())
        activity_count = conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE kind='job-file-archived'"
        ).fetchone()[0]
    assert lock_after == lock_before
    assert activity_count == 0


def test_archive_is_the_only_file_removal_service():
    """Retained work items must not expose a destructive deletion API."""
    assert not hasattr(job_files, "delete_file_permanently")


def test_peer_approval_is_bound_to_exact_current_version(tmp_path):
    """Approval identifies both the immutable version and its peer reviewer."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    version = job_files.get_current_version(
        attached["id"], "editor@example.edu"
    )
    collaboration.acquire_file_checkout(
        attached["id"], "editor@example.edu"
    )

    approved = job_files.approve_current(
        attached["id"],
        by="editor@example.edu",
        opened_version_id=version["id"],
    )

    assert approved["status"] == "approved"
    assert approved["current_version"]["approval_kind"] == "peer-approved"
    assert approved["current_version"]["approved_by"] == "editor@example.edu"
    assert approved["current_version"]["id"] == version["id"]


def test_approval_rejects_stale_opened_version_without_mutating_file(tmp_path):
    """A reviewer cannot approve a version other than the one they opened."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")

    with pytest.raises(job_files.JobFileError, match="changed"):
        job_files.approve_current(
            attached["id"],
            by="owner@example.edu",
            opened_version_id=int(attached["current_version_id"]) + 1,
        )

    current = job_files.get_current_version(
        attached["id"], "owner@example.edu"
    )
    assert current["approval_kind"] is None
    assert job_files.get_file(
        attached["id"], "owner@example.edu"
    )["status"] == "in_progress"


def test_approval_cannot_overwrite_existing_immutable_approval(tmp_path):
    """One version keeps the first approval identity recorded against it."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")
    approved = job_files.approve_current(
        attached["id"],
        by="owner@example.edu",
        opened_version_id=attached["current_version_id"],
    )
    collaboration.release_file_checkout(attached["id"], "owner@example.edu")
    collaboration.acquire_file_checkout(attached["id"], "editor@example.edu")

    with pytest.raises(job_files.JobFileError, match="already approved"):
        job_files.approve_current(
            attached["id"],
            by="editor@example.edu",
            opened_version_id=approved["current_version_id"],
        )

    unchanged = job_files.get_current_version(
        attached["id"], "owner@example.edu"
    )
    assert unchanged["approval_kind"] == "self-approved"
    assert unchanged["approved_by"] == "owner@example.edu"


def test_approved_file_cannot_be_returned_for_review(tmp_path):
    """Return is only the in-progress handoff and cannot erase approval state."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")
    approved = job_files.approve_current(
        attached["id"],
        by="owner@example.edu",
        opened_version_id=attached["current_version_id"],
    )
    before_activity = len(
        jobs.list_activity(job["id"], user_email="owner@example.edu")
    )

    with pytest.raises(job_files.JobFileError, match="in-progress"):
        job_files.return_for_review(
            attached["id"],
            by="owner@example.edu",
            opened_version_id=approved["current_version_id"],
        )

    unchanged = job_files.get_file(attached["id"], "owner@example.edu")
    version = job_files.get_current_version(attached["id"], "owner@example.edu")
    assert unchanged["status"] == "approved"
    assert version["approval_kind"] == "self-approved"
    assert len(
        jobs.list_activity(job["id"], user_email="owner@example.edu")
    ) == before_activity
    assert collaboration.release_file_checkout(
        attached["id"], "owner@example.edu"
    ) is True


def test_request_changes_scopes_required_note_and_releases_checkout(tmp_path):
    """Change requests stay with the reviewed file/version and end review lease."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    first = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    second = attach_fixture(job["id"], tmp_path, "fresh.mrc", b"two")
    collaboration.acquire_file_checkout(first["id"], "owner@example.edu")
    job_files.return_for_review(
        first["id"],
        by="owner@example.edu",
        opened_version_id=first["current_version_id"],
    )
    collaboration.acquire_file_checkout(first["id"], "owner@example.edu")

    changed = job_files.request_changes(
        first["id"],
        by="owner@example.edu",
        opened_version_id=first["current_version_id"],
        note="Check leader",
    )

    assert changed["status"] == "changes_requested"
    assert jobs.list_review_notes(
        job["id"], user_email="owner@example.edu", job_file_id=second["id"]
    ) == []
    notes = jobs.list_review_notes(
        job["id"], user_email="owner@example.edu", job_file_id=first["id"]
    )
    assert [(row["note"], row["job_file_version_id"]) for row in notes] == [
        ("Check leader", first["current_version_id"])
    ]
    assert collaboration.release_file_checkout(
        first["id"], "owner@example.edu"
    ) is False


def test_request_changes_requires_review_state(tmp_path):
    """A change request is a review outcome, not a generic status override."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")

    with pytest.raises(job_files.JobFileError, match="needs review"):
        job_files.request_changes(
            attached["id"],
            by="owner@example.edu",
            opened_version_id=attached["current_version_id"],
            note="Check leader",
        )

    assert job_files.get_file(
        attached["id"], "owner@example.edu"
    )["status"] == "in_progress"


def test_approved_file_can_be_completed_only_by_exact_checkout_holder(tmp_path):
    """Completion is explicit, exact-version, and starts from release-ready state."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")
    approved = job_files.approve_current(
        attached["id"],
        by="owner@example.edu",
        opened_version_id=attached["current_version_id"],
    )

    completed = job_files.set_complete(
        attached["id"],
        by="owner@example.edu",
        opened_version_id=approved["current_version_id"],
    )

    assert completed["status"] == "complete"


def test_list_versions_is_file_scoped_and_oldest_first(tmp_path):
    """Immutable review history cannot include another file's version rows."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    first = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    second = attach_fixture(job["id"], tmp_path, "fresh.mrc", b"two")

    rows = job_files.list_versions(first["id"], "owner@example.edu")

    assert [(row["job_file_id"], row["version_number"]) for row in rows] == [
        (first["id"], 1)
    ]
    assert all(row["job_file_id"] != second["id"] for row in rows)


def test_new_version_preserves_historical_approval(tmp_path):
    """A later current version invalidates active state, not approval history."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    source = Path("tests/fixtures/sample.mrc")
    attached = job_files.attach_file(
        job_id=job["id"],
        user_email="owner@example.edu",
        source_path=source,
        filename="sample.mrc",
        record_count=7,
        file_bytes=source.stat().st_size,
    )
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")
    approved = job_files.approve_current(
        attached["id"],
        by="owner@example.edu",
        opened_version_id=attached["current_version_id"],
    )
    old = approved["current_version"]
    candidate = tmp_path / "candidate.mrc"
    shutil.copyfile(source, candidate)

    new = job_files.adopt_candidate(
        file_id=attached["id"],
        opened_version_id=old["id"],
        user_email="owner@example.edu",
        candidate_path=candidate,
        source_kind="restore",
        label="Restore original",
    )

    assert job_files.get_file(
        attached["id"], "owner@example.edu"
    )["status"] == "in_progress"
    assert job_files.get_version(
        old["id"], "owner@example.edu"
    )["approval_kind"] == "self-approved"
    assert new["approval_kind"] is None
