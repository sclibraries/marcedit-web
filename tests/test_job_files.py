"""Durable per-file work item tests for TASK-151."""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import job_files, jobs


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
    from marcedit_web.lib import db

    with db.connect() as conn:
        conn.execute(
            "UPDATE job_files SET archived_by=?, archived_at=? WHERE id=?",
            ("owner@example.edu", "2026-07-14T12:00:00Z", attached["id"]),
        )

    assert job_files.list_files(job["id"], "owner@example.edu") == []
    assert [row["id"] for row in job_files.list_files(
        job["id"], "owner@example.edu", include_archived=True
    )] == [attached["id"]]
