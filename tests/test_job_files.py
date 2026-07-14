"""Durable per-file work item tests for TASK-151."""

from __future__ import annotations

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
