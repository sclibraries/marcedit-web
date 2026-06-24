"""Tests for marcedit_web.lib.upload_persistence (TASK-051)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from marcedit_web.lib import db, upload_persistence


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def _record(user="alice@example.edu", filename="test.mrc", path="/tmp/x.mrc",
            records=10, size=1024):
    upload_persistence.record_upload(
        user=user,
        filename=filename,
        file_path=path,
        record_count=records,
        file_bytes=size,
    )


def test_record_and_get_round_trip():
    _record()
    row = upload_persistence.get_active_upload("alice@example.edu")
    assert row is not None
    assert row["filename"] == "test.mrc"
    assert row["file_path"] == "/tmp/x.mrc"
    assert row["record_count"] == 10
    assert row["file_bytes"] == 1024
    assert row["active"] == 1


def test_get_returns_none_when_no_active_row():
    assert upload_persistence.get_active_upload("alice@example.edu") is None


def test_anonymous_user_is_noop():
    upload_persistence.record_upload(
        user="anonymous",
        filename="anon.mrc",
        file_path="/tmp/x.mrc",
        record_count=1,
        file_bytes=10,
    )
    # No row inserted at all.
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
    assert n == 0
    assert upload_persistence.get_active_upload("anonymous") is None


def test_recording_supersedes_previous_active_row():
    _record(filename="first.mrc")
    first = upload_persistence.get_active_upload("alice@example.edu")
    _record(filename="second.mrc")
    second = upload_persistence.get_active_upload("alice@example.edu")

    assert first["filename"] == "first.mrc"
    assert second["filename"] == "second.mrc"
    assert second["id"] != first["id"]

    with db.connect() as conn:
        active = list(conn.execute(
            "SELECT id, filename FROM uploads"
            " WHERE user_email = ? AND active = 1",
            ("alice@example.edu",),
        ))
        inactive = list(conn.execute(
            "SELECT filename FROM uploads"
            " WHERE user_email = ? AND active = 0",
            ("alice@example.edu",),
        ))
    # Exactly one active row per user at any time.
    assert len(active) == 1
    assert active[0]["filename"] == "second.mrc"
    assert {r["filename"] for r in inactive} == {"first.mrc"}


def test_concurrent_uploads_leave_one_active_row_per_user():
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker(i: int) -> None:
        try:
            barrier.wait()
            _record(filename=f"batch-{i}.mrc", path=f"/tmp/batch-{i}.mrc")
        except BaseException as exc:  # pragma: no cover - re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with db.connect() as conn:
        active = list(conn.execute(
            "SELECT filename FROM uploads"
            " WHERE user_email=? AND active=1",
            ("alice@example.edu",),
        ))
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM uploads WHERE user_email=?",
            ("alice@example.edu",),
        ).fetchone()["n"]
    assert len(active) == 1
    assert total == 8


def test_active_rows_are_per_user():
    _record(user="alice@example.edu", filename="a.mrc")
    _record(user="bob@example.edu", filename="b.mrc")
    assert (
        upload_persistence.get_active_upload("alice@example.edu")["filename"]
        == "a.mrc"
    )
    assert (
        upload_persistence.get_active_upload("bob@example.edu")["filename"]
        == "b.mrc"
    )


def test_concurrent_uploads_for_different_users_each_keep_active_row():
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def worker(i: int) -> None:
        try:
            user = f"user-{i}@example.edu"
            barrier.wait()
            _record(user=user, filename=f"{i}.mrc", path=f"/tmp/{i}.mrc")
        except BaseException as exc:  # pragma: no cover - re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with db.connect() as conn:
        active = list(conn.execute(
            "SELECT user_email, filename FROM uploads WHERE active=1"
        ))
    assert len(active) == 6
    assert {row["user_email"] for row in active} == {
        f"user-{i}@example.edu" for i in range(6)
    }


def test_clear_active_upload_removes_file_and_flips_row(tmp_path):
    path = tmp_path / "upload.mrc"
    path.write_bytes(b"x")
    _record(path=str(path))
    upload_persistence.clear_active_upload("alice@example.edu")

    assert upload_persistence.get_active_upload("alice@example.edu") is None
    assert not path.exists()
    with db.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM uploads WHERE user_email = ? AND active = 1",
            ("alice@example.edu",),
        ).fetchone()[0]
    assert n == 0


def test_clear_active_upload_handles_missing_file(tmp_path):
    """Already-missing on-disk file shouldn't trip clear."""
    path = tmp_path / "gone.mrc"
    _record(path=str(path))  # file never existed
    upload_persistence.clear_active_upload("alice@example.edu")
    assert upload_persistence.get_active_upload("alice@example.edu") is None


def test_clear_active_upload_anonymous_noop():
    # Must not raise even when there's no row to find.
    upload_persistence.clear_active_upload("anonymous")


def test_persisted_upload_dir_uses_safe_slug(monkeypatch, tmp_path):
    """Dir name derives from safe_user_slug — no path traversal."""
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    target = upload_persistence.persisted_upload_dir("../../etc/passwd")
    assert target.is_dir()
    # The slug strips the traversal sequence.
    assert ".." not in target.name
    assert target.parent == tmp_path / "u"
