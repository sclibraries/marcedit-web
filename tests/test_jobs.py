"""Tests for server-side job/project helpers (TASK-081)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import db, jobs, upload_persistence


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def test_ensure_default_job_is_idempotent():
    """Every user gets one stable personal job for legacy/default uploads."""
    first = jobs.ensure_default_job("alice@example.edu")
    second = jobs.ensure_default_job("alice@example.edu")

    assert second["id"] == first["id"]
    assert first["name"] == "Personal uploads"
    assert first["owner_email"] == "alice@example.edu"
    assert first["visibility"] == "private"


def test_create_and_list_named_jobs():
    """Users can create named server-side jobs before sharing UI exists."""
    created = jobs.create_job("alice@example.edu", "Vendor load June")

    listed = jobs.list_jobs("alice@example.edu")

    assert created["name"] == "Vendor load June"
    assert [job["name"] for job in listed] == ["Vendor load June"]


def test_create_job_rejects_duplicate_owner_name():
    jobs.create_job("alice@example.edu", "Vendor load June")

    with pytest.raises(jobs.JobError):
        jobs.create_job("alice@example.edu", "Vendor load June")


def test_record_upload_attaches_to_default_job():
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="load.mrc",
        file_path="/tmp/load.mrc",
        record_count=2,
        file_bytes=100,
    )

    row = upload_persistence.get_active_upload("alice@example.edu")
    default_job = jobs.ensure_default_job("alice@example.edu")

    assert row["job_id"] == default_job["id"]


def test_record_upload_can_attach_to_named_job():
    job = jobs.create_job("alice@example.edu", "Vendor load June")

    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="load.mrc",
        file_path="/tmp/load.mrc",
        record_count=2,
        file_bytes=100,
        job_id=job["id"],
    )

    row = upload_persistence.get_active_upload("alice@example.edu")
    assert row["job_id"] == job["id"]


def test_list_job_uploads_returns_all_files_for_job():
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="first.mrc",
        file_path="/tmp/first.mrc",
        record_count=2,
        file_bytes=100,
        job_id=job["id"],
    )
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="second.mrc",
        file_path="/tmp/second.mrc",
        record_count=3,
        file_bytes=200,
        job_id=job["id"],
    )

    uploads = jobs.list_job_uploads(job["id"])

    assert [row["filename"] for row in uploads] == ["first.mrc", "second.mrc"]
