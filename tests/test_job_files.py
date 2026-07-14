"""Durable per-file work item tests for TASK-151."""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import authz, db, job_files, jobs


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
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO advisory_locks(resource_type,resource_id,holder_email,"
            "expires_at,created_at,updated_at) VALUES('job-file',?,?,?,?,?)",
            (
                str(attached["id"]),
                "owner@example.edu",
                "2099-01-01T00:00:00Z",
                "2026-07-14T12:00:00Z",
                "2026-07-14T12:00:00Z",
            ),
        )

    archived = job_files.archive_file(attached["id"], by="owner@example.edu")

    assert archived["archived_by"] == "owner@example.edu"
    assert archived["archived_at"] is not None
    assert version_path.read_bytes() == b"one"
    with db.connect() as conn:
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


def test_permanent_delete_requires_administrator(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")

    with pytest.raises(job_files.JobFileError, match="administrator"):
        job_files.delete_file_permanently(
            attached["id"], by="owner@example.edu"
        )


def test_permanent_delete_refuses_file_with_retained_export(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    version = job_files.get_current_version(attached["id"], "owner@example.edu")
    authz.approve_user(
        "owner@example.edu", by="bootstrap@example.edu", role="admin"
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO job_file_exports(job_file_id,version_id,purpose,description,"
            "filename,file_path,record_count,validation_json,state,created_by,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                attached["id"],
                version["id"],
                "EDS deletion load",
                "",
                "export.mrc",
                str(tmp_path / "export.mrc"),
                1,
                "{}",
                "draft",
                "owner@example.edu",
                "2026-07-14T20:00:00Z",
            ),
        )

    with pytest.raises(job_files.JobFileError, match="versions or exports"):
        job_files.delete_file_permanently(
            attached["id"], by="owner@example.edu"
        )

    assert Path(version["file_path"]).exists()


def test_permanent_delete_removes_metadata_and_original_bytes(tmp_path):
    """A confirmed admin deletion removes both halves of the work item."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    version = job_files.get_current_version(attached["id"], "owner@example.edu")
    version_path = Path(version["file_path"])
    authz.approve_user(
        "owner@example.edu", by="bootstrap@example.edu", role="admin"
    )

    job_files.delete_file_permanently(attached["id"], by="owner@example.edu")

    assert not version_path.exists()
    with pytest.raises(job_files.JobFileError, match="job file not found"):
        job_files.get_file(attached["id"], "owner@example.edu")
    with db.connect() as conn:
        activity = conn.execute(
            "SELECT kind FROM job_activity ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert activity["kind"] == "job-file-deleted"


def test_permanent_delete_unlink_failure_preserves_metadata_and_bytes(
    tmp_path, monkeypatch,
):
    """Filesystem failure must leave a complete work item that can be retried."""
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    version = job_files.get_current_version(attached["id"], "owner@example.edu")
    version_path = Path(version["file_path"])
    authz.approve_user(
        "owner@example.edu", by="bootstrap@example.edu", role="admin"
    )
    original_unlink = Path.unlink

    def fail_version_unlink(path, *args, **kwargs):
        if path == version_path:
            raise OSError("immutable storage unavailable")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_version_unlink)

    with pytest.raises(OSError, match="immutable storage unavailable"):
        job_files.delete_file_permanently(
            attached["id"], by="owner@example.edu"
        )

    assert version_path.read_bytes() == b"one"
    assert job_files.get_file(
        attached["id"], "owner@example.edu"
    )["current_version_id"] == version["id"]
    assert job_files.get_version(
        version["id"], "owner@example.edu"
    )["file_path"] == str(version_path)
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE kind='job-file-deleted'"
        ).fetchone()[0] == 0


def test_unlink_restores_original_bytes_when_database_commit_fails(tmp_path):
    """A commit failure must not leave retained metadata pointing at no file."""
    version_path = tmp_path / "v000001.mrc"
    version_path.write_bytes(b"one")

    class FailingCommit:
        def commit(self):
            raise RuntimeError("database storage unavailable")

    with pytest.raises(RuntimeError, match="database storage unavailable"):
        job_files._unlink_and_commit(FailingCommit(), version_path)

    assert version_path.read_bytes() == b"one"
