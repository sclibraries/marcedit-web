"""Collaboration lock/version service tests (TASK-094)."""

from __future__ import annotations

import datetime as dt
import threading
from contextlib import contextmanager

import pytest

from marcedit_web.lib import collaboration, db, job_files, jobs


OWNER = "owner@example.edu"
EDITOR = "editor@example.edu"
VIEWER = "viewer@example.edu"


@pytest.fixture(autouse=True)
def _schema(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))
    db.init_schema()


def _attach_file(job_id, tmp_path, filename):
    source = tmp_path / filename
    source.write_bytes(filename.encode())
    return job_files.attach_file(
        job_id=job_id,
        user_email=OWNER,
        source_path=source,
        filename=filename,
        record_count=1,
        file_bytes=source.stat().st_size,
    )


@pytest.fixture
def shared_file(tmp_path):
    job = jobs.create_job(OWNER, "Shared files")
    jobs.grant_access(job["id"], EDITOR, "editor", by=OWNER)
    jobs.grant_access(job["id"], VIEWER, "viewer", by=OWNER)
    return _attach_file(job["id"], tmp_path, "shared.mrc")


@pytest.fixture
def job_with_two_files(tmp_path):
    job = jobs.create_job(OWNER, "Two files")
    jobs.grant_access(job["id"], EDITOR, "editor", by=OWNER)
    return (
        _attach_file(job["id"], tmp_path, "first.mrc"),
        _attach_file(job["id"], tmp_path, "second.mrc"),
    )


def test_different_catalogers_can_check_out_different_files(job_with_two_files):
    first, second = job_with_two_files

    assert collaboration.acquire_file_checkout(first["id"], OWNER).acquired
    assert collaboration.acquire_file_checkout(second["id"], EDITOR).acquired


def test_second_cataloger_can_view_but_not_check_out_same_file(shared_file):
    assert collaboration.acquire_file_checkout(shared_file["id"], OWNER).acquired

    decision = collaboration.acquire_file_checkout(shared_file["id"], EDITOR)

    assert decision.acquired is False
    assert decision.holder_email == OWNER
    assert job_files.get_file(shared_file["id"], EDITOR)["id"] == shared_file["id"]


def test_force_release_requires_owner(shared_file):
    collaboration.acquire_file_checkout(shared_file["id"], EDITOR)

    with pytest.raises(collaboration.CollaborationError, match="owner"):
        collaboration.force_release_file_checkout(shared_file["id"], by=EDITOR)

    assert collaboration.force_release_file_checkout(shared_file["id"], by=OWNER)


def test_viewer_cannot_check_out_file(shared_file):
    with pytest.raises(collaboration.CollaborationError, match="editor"):
        collaboration.acquire_file_checkout(shared_file["id"], VIEWER)


def test_archived_file_cannot_be_checked_out_or_locked(shared_file):
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_files SET archived_by=?, archived_at=? WHERE id=?",
            (OWNER, "2026-07-14T12:00:00Z", shared_file["id"]),
        )

    with pytest.raises(collaboration.CollaborationError, match="archived"):
        collaboration.acquire_file_checkout(shared_file["id"], OWNER)

    with db.connect() as conn:
        assert conn.execute(
            "SELECT 1 FROM advisory_locks WHERE resource_type='job-file'"
            " AND resource_id=?",
            (str(shared_file["id"]),),
        ).fetchone() is None


def test_checkout_rechecks_archived_state_after_waiting_for_writer(
    shared_file, monkeypatch
):
    original_connect = db.connect
    begin_attempted = threading.Event()
    result: list[object] = []

    with original_connect() as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE job_files SET archived_by=?, archived_at=? WHERE id=?",
            (OWNER, "2026-07-14T12:00:00Z", shared_file["id"]),
        )

        @contextmanager
        def traced_connect():
            with original_connect() as conn:
                conn.set_trace_callback(
                    lambda statement: begin_attempted.set()
                    if statement == "BEGIN IMMEDIATE"
                    else None
                )
                yield conn

        monkeypatch.setattr(collaboration.db, "connect", traced_connect)

        def acquire():
            try:
                collaboration.acquire_file_checkout(shared_file["id"], OWNER)
            except Exception as exc:  # captured for assertion in this thread
                result.append(exc)

        thread = threading.Thread(target=acquire)
        thread.start()
        assert begin_attempted.wait(timeout=2)

    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(result) == 1
    assert isinstance(result[0], collaboration.CollaborationError)
    assert "archived" in str(result[0])
    with original_connect() as conn:
        assert conn.execute(
            "SELECT 1 FROM advisory_locks WHERE resource_type='job-file'"
            " AND resource_id=?",
            (str(shared_file["id"]),),
        ).fetchone() is None


def test_checkout_uses_time_captured_after_waiting_for_writer(
    shared_file, monkeypatch
):
    original_connect = db.connect
    begin_attempted = threading.Event()
    writer_released = threading.Event()
    result: list[object] = []
    with original_connect() as conn:
        conn.execute(
            "INSERT INTO advisory_locks(resource_type,resource_id,holder_email,"
            " expires_at,created_at,updated_at) VALUES('job-file',?,?,?,?,?)",
            (
                str(shared_file["id"]),
                OWNER,
                "2050-01-01T00:00:00Z",
                "2000-01-01T00:00:00Z",
                "2000-01-01T00:00:00Z",
            ),
        )

    with original_connect() as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE job_files SET description='writer held transaction' WHERE id=?",
            (shared_file["id"],),
        )

        @contextmanager
        def traced_connect():
            with original_connect() as conn:
                conn.set_trace_callback(
                    lambda statement: begin_attempted.set()
                    if statement == "BEGIN IMMEDIATE"
                    else None
                )
                yield conn

        monkeypatch.setattr(collaboration.db, "connect", traced_connect)
        monkeypatch.setattr(
            collaboration,
            "_now",
            lambda: dt.datetime(2100 if writer_released.is_set() else 2000, 1, 1),
        )

        thread = threading.Thread(
            target=lambda: result.append(
                collaboration.acquire_file_checkout(shared_file["id"], EDITOR)
            )
        )
        thread.start()
        assert begin_attempted.wait(timeout=2)

    writer_released.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result[0].acquired is True
    assert result[0].holder_email == EDITOR


def test_file_checkout_assertion_requires_holder_and_opened_version(shared_file):
    collaboration.acquire_file_checkout(shared_file["id"], OWNER)
    opened_version_id = int(shared_file["current_version_id"])

    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        collaboration._assert_file_checkout_in_tx(
            conn, shared_file["id"], OWNER, opened_version_id
        )

    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(collaboration.CollaborationError, match="checkout"):
            collaboration._assert_file_checkout_in_tx(
                conn, shared_file["id"], EDITOR, opened_version_id
            )

    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(collaboration.CollaborationError, match="changed"):
            collaboration._assert_file_checkout_in_tx(
                conn, shared_file["id"], OWNER, opened_version_id + 1
            )


def test_checkout_updates_editing_status_and_return_for_review_releases(shared_file):
    decision = collaboration.acquire_file_checkout(shared_file["id"], OWNER)

    assert decision.acquired
    assert job_files.get_file(shared_file["id"], OWNER)["status"] == "in_progress"
    assert collaboration.return_file_for_review(shared_file["id"], OWNER)
    assert job_files.get_file(shared_file["id"], OWNER)["status"] == "needs_review"
    assert collaboration.release_file_checkout(shared_file["id"], OWNER) is False


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
