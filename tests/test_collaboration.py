"""Collaboration lock/version service tests (TASK-094)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import collaboration, db, jobs


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def test_current_job_version_starts_at_zero_and_bumps():
    job = jobs.create_job("owner@example.edu", "Shared load")

    assert collaboration.current_job_version(job["id"]) == 0
    assert collaboration.bump_job_version(job["id"]) == 1
    assert collaboration.current_job_version(job["id"]) == 1


def test_record_resource_id_uses_cataloger_record_numbering():
    assert collaboration.record_resource_id(42, 3) == "42:3"


def test_record_lock_fails_while_job_lock_active():
    job = jobs.create_job("owner@example.edu", "Shared load")
    assert collaboration.acquire_job_lock(job["id"], "owner@example.edu").acquired

    decision = collaboration.acquire_record_lock(
        job["id"],
        1,
        "owner@example.edu",
    )

    assert decision.acquired is False
    assert decision.holder_email == "owner@example.edu"


def test_job_lock_fails_while_record_lock_active():
    job = jobs.create_job("owner@example.edu", "Shared load")
    assert collaboration.acquire_record_lock(
        job["id"], 1, "owner@example.edu"
    ).acquired

    decision = collaboration.acquire_job_lock(job["id"], "owner@example.edu")

    assert decision.acquired is False
    assert decision.holder_email == "owner@example.edu"


def test_expired_record_lock_can_be_reacquired_by_editor():
    job = jobs.create_job("owner@example.edu", "Shared load")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )
    assert collaboration.acquire_record_lock(
        job["id"], 1, "owner@example.edu", ttl_seconds=-1,
    ).acquired

    decision = collaboration.acquire_record_lock(
        job["id"], 1, "editor@example.edu",
    )

    assert decision.acquired is True
    assert decision.holder_email == "editor@example.edu"


def test_viewer_cannot_acquire_record_lock():
    job = jobs.create_job("owner@example.edu", "Shared load")
    jobs.grant_access(
        job["id"],
        "viewer@example.edu",
        "viewer",
        by="owner@example.edu",
    )

    with pytest.raises(collaboration.CollaborationError, match="editor"):
        collaboration.acquire_record_lock(job["id"], 1, "viewer@example.edu")


def test_only_holder_can_release_record_lock():
    job = jobs.create_job("owner@example.edu", "Shared load")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )
    assert collaboration.acquire_record_lock(
        job["id"], 1, "owner@example.edu",
    ).acquired

    assert collaboration.release_record_lock(
        job["id"], 1, "editor@example.edu",
    ) is False
    assert collaboration.release_record_lock(
        job["id"], 1, "owner@example.edu",
    ) is True


def test_assert_can_save_record_blocks_stale_version():
    job = jobs.create_job("owner@example.edu", "Shared load")
    assert collaboration.acquire_record_lock(
        job["id"], 1, "owner@example.edu",
    ).acquired
    opened = collaboration.current_job_version(job["id"])
    collaboration.bump_job_version(job["id"])

    with pytest.raises(collaboration.CollaborationError, match="changed"):
        collaboration.assert_can_save_record(
            job["id"],
            1,
            "owner@example.edu",
            opened,
        )


def test_assert_can_save_record_blocks_non_holder():
    job = jobs.create_job("owner@example.edu", "Shared load")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )
    assert collaboration.acquire_record_lock(
        job["id"], 1, "owner@example.edu",
    ).acquired
    opened = collaboration.current_job_version(job["id"])

    with pytest.raises(collaboration.CollaborationError, match="lock"):
        collaboration.assert_can_save_record(
            job["id"],
            1,
            "editor@example.edu",
            opened,
        )
