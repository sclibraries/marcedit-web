"""Atomic immutable job-file version adoption (TASK-151)."""

from __future__ import annotations

import errno
import io
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pymarc
import pytest

from marcedit_web.lib import collaboration, db, job_files, jobs, session


OWNER = "owner@example.edu"


def _marc_bytes(record) -> bytes:
    target = io.BytesIO()
    writer = pymarc.MARCWriter(target)
    writer.write(record)
    return target.getvalue()


@pytest.fixture(autouse=True)
def _job_files_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))


@pytest.fixture
def checked_out_file(tmp_path, record):
    source = tmp_path / "original.mrc"
    source.write_bytes(_marc_bytes(record))
    job = jobs.create_job(OWNER, "Routledge")
    attached = job_files.attach_file(
        job_id=job["id"],
        user_email=OWNER,
        source_path=source,
        filename="deletes.mrc",
        record_count=1,
        file_bytes=source.stat().st_size,
    )
    collaboration.acquire_file_checkout(attached["id"], OWNER)
    return attached


@pytest.fixture
def candidate(tmp_path, record):
    path = tmp_path / "candidate.mrc"
    path.write_bytes(_marc_bytes(record))
    return path


def _adopt(attached, candidate_path, *, opened_version_id=None):
    return job_files.adopt_candidate(
        file_id=attached["id"],
        opened_version_id=(
            attached["current_version_id"]
            if opened_version_id is None
            else opened_version_id
        ),
        user_email=OWNER,
        candidate_path=candidate_path,
        source_kind="quick-batch",
        label="Set leader status to deleted",
        summary={"changed": 1},
        validation={"errors": 0},
    )


def test_adopt_candidate_creates_version_and_swaps_current(
    checked_out_file, candidate,
):
    before = job_files.get_current_version(checked_out_file["id"], OWNER)

    created = _adopt(checked_out_file, candidate)

    assert created["version_number"] == 2
    assert created["parent_version_id"] == before["id"]
    assert created["summary_json"] == '{"changed": 1}'
    assert created["validation_json"] == '{"errors": 0}'
    assert job_files.get_current_version(
        checked_out_file["id"], OWNER
    )["id"] == created["id"]
    assert Path(before["file_path"]).exists()
    assert not candidate.exists()


def test_adopt_candidate_stages_cross_filesystem_candidate(
    checked_out_file, candidate, monkeypatch,
):
    """Preview paths may be on /tmp while durable versions are bind-mounted."""
    real_replace = job_files.os.replace

    def reject_cross_filesystem_replace(source, target):
        if Path(source) == candidate:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_replace(source, target)

    monkeypatch.setattr(job_files.os, "replace", reject_cross_filesystem_replace)

    created = _adopt(checked_out_file, candidate)

    assert Path(created["file_path"]).exists()
    assert not candidate.exists()


@pytest.mark.parametrize("failure", ["lost_checkout", "stale_version", "invalid_marc"])
def test_failed_adoption_preserves_current_and_removes_candidate(
    failure, checked_out_file, candidate,
):
    before_id = checked_out_file["current_version_id"]
    opened_version_id = before_id
    if failure == "lost_checkout":
        collaboration.release_file_checkout(checked_out_file["id"], OWNER)
    elif failure == "stale_version":
        opened_version_id += 1
    else:
        candidate.write_bytes(b"not MARC")

    with pytest.raises(job_files.JobFileError):
        _adopt(
            checked_out_file,
            candidate,
            opened_version_id=opened_version_id,
        )

    assert job_files.get_current_version(
        checked_out_file["id"], OWNER
    )["id"] == before_id
    assert not candidate.exists()
    assert not (job_files.versions_root() / str(checked_out_file["id"])
                / "versions" / "v000002.mrc").exists()


def test_adoption_rejects_partially_malformed_candidate(
    checked_out_file, candidate,
):
    before_id = checked_out_file["current_version_id"]
    candidate.write_bytes(candidate.read_bytes() + b"00100abc")

    with pytest.raises(job_files.JobFileError, match="malformed"):
        _adopt(checked_out_file, candidate)

    assert job_files.get_current_version(
        checked_out_file["id"], OWNER
    )["id"] == before_id
    assert not candidate.exists()


def test_adoption_rejects_framed_record_that_pymarc_cannot_parse(
    checked_out_file, candidate,
):
    """A plausible record length must not substitute for MARC parsing."""
    malformed = bytearray(candidate.read_bytes())
    malformed[12:17] = b"99999"
    candidate.write_bytes(malformed)

    with pytest.raises(job_files.JobFileError, match="malformed"):
        _adopt(checked_out_file, candidate)

    assert job_files.get_current_version(
        checked_out_file["id"], OWNER
    )["id"] == checked_out_file["current_version_id"]
    assert not candidate.exists()


@pytest.mark.parametrize("access_change", ["revoked", "viewer"])
def test_adoption_rechecks_editor_access_inside_transaction(
    access_change, checked_out_file, candidate,
):
    editor = "editor@example.edu"
    jobs.grant_access(
        checked_out_file["job_id"],
        editor,
        "editor",
        by=OWNER,
    )
    collaboration.release_file_checkout(checked_out_file["id"], OWNER)
    collaboration.acquire_file_checkout(checked_out_file["id"], editor)
    if access_change == "revoked":
        jobs.revoke_access(checked_out_file["job_id"], editor, by=OWNER)
    else:
        jobs.grant_access(
            checked_out_file["job_id"],
            editor,
            "viewer",
            by=OWNER,
        )

    with pytest.raises(job_files.JobFileError, match="owner or editor"):
        job_files.adopt_candidate(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=editor,
            candidate_path=candidate,
            source_kind="quick-batch",
            label="Set leader status to deleted",
        )

    assert job_files.get_current_version(
        checked_out_file["id"], OWNER
    )["id"] == checked_out_file["current_version_id"]
    assert not candidate.exists()


def test_post_rename_failure_rolls_back_database_and_removes_artifacts(
    checked_out_file, candidate, monkeypatch,
):
    """A failed pointer CAS must not strand a row or renamed candidate."""
    original_connect = db.connect

    class FailingConnection:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, parameters=()):
            if sql.startswith("UPDATE job_files SET current_version_id="):
                raise RuntimeError("pointer update failed")
            return self._conn.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    @contextmanager
    def failing_connect():
        with original_connect() as conn:
            yield FailingConnection(conn)

    monkeypatch.setattr(db, "connect", failing_connect)

    with pytest.raises(RuntimeError, match="pointer update failed"):
        _adopt(checked_out_file, candidate)

    with original_connect() as conn:
        file_row = conn.execute(
            "SELECT current_version_id FROM job_files WHERE id=?",
            (checked_out_file["id"],),
        ).fetchone()
        version_count = conn.execute(
            "SELECT COUNT(*) FROM job_file_versions WHERE job_file_id=?",
            (checked_out_file["id"],),
        ).fetchone()[0]
    assert file_row["current_version_id"] == checked_out_file["current_version_id"]
    assert version_count == 1
    assert not candidate.exists()
    assert not (job_files.versions_root() / str(checked_out_file["id"])
                / "versions" / "v000002.mrc").exists()


def _fail_first_connection_commit(
    monkeypatch,
    *,
    persist_before_raise,
    after_persist=None,
):
    original_connect = db.connect
    first = True

    @contextmanager
    def failing_connect():
        nonlocal first
        if not first:
            with original_connect() as conn:
                yield conn
            return
        first = False
        conn = sqlite3.connect(db.db_path(), isolation_level="DEFERRED")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            if persist_before_raise:
                conn.commit()
                if after_persist is not None:
                    after_persist()
                raise RuntimeError("commit persisted but confirmation failed")
            raise RuntimeError("commit failed before persistence")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(db, "connect", failing_connect)


def test_commit_failure_before_persistence_cleans_uncommitted_target(
    checked_out_file, candidate, monkeypatch,
):
    before = job_files.get_current_version(checked_out_file["id"], OWNER)
    _fail_first_connection_commit(monkeypatch, persist_before_raise=False)

    with pytest.raises(RuntimeError, match="commit failed before persistence"):
        _adopt(checked_out_file, candidate)

    current = job_files.get_current_version(checked_out_file["id"], OWNER)
    assert current["id"] == before["id"]
    assert Path(before["file_path"]).exists()
    assert not candidate.exists()
    assert not (job_files.versions_root() / str(checked_out_file["id"])
                / "versions" / "v000002.mrc").exists()


def test_commit_persisted_then_raised_retains_committed_target(
    checked_out_file, candidate, monkeypatch,
):
    before = job_files.get_current_version(checked_out_file["id"], OWNER)
    _fail_first_connection_commit(monkeypatch, persist_before_raise=True)

    with pytest.raises(
        job_files.JobFileError,
        match="adopted.*confirmation failed",
    ):
        _adopt(checked_out_file, candidate)

    current = job_files.get_current_version(checked_out_file["id"], OWNER)
    assert current["id"] != before["id"]
    assert current["parent_version_id"] == before["id"]
    assert Path(current["file_path"]).exists()
    assert Path(before["file_path"]).exists()
    assert not candidate.exists()


def test_commit_reconciliation_retains_version_advanced_to_history(
    checked_out_file, candidate, monkeypatch, tmp_path,
):
    """A later current version must not make committed parent bytes disposable."""
    before = job_files.get_current_version(checked_out_file["id"], OWNER)
    later_candidate = tmp_path / "later-candidate.mrc"
    later_candidate.write_bytes(candidate.read_bytes())
    adopted = {}

    def advance_current():
        historical = job_files.get_current_version(checked_out_file["id"], OWNER)
        adopted["historical"] = historical
        adopted["later"] = job_files.adopt_candidate(
            file_id=checked_out_file["id"],
            opened_version_id=historical["id"],
            user_email=OWNER,
            candidate_path=later_candidate,
            source_kind="task",
            label="Later valid adoption",
        )

    _fail_first_connection_commit(
        monkeypatch,
        persist_before_raise=True,
        after_persist=advance_current,
    )

    with pytest.raises(job_files.JobFileError, match="confirmation failed"):
        _adopt(checked_out_file, candidate)

    historical = job_files.get_version(adopted["historical"]["id"], OWNER)
    current = job_files.get_current_version(checked_out_file["id"], OWNER)
    assert historical["parent_version_id"] == before["id"]
    assert Path(historical["file_path"]).exists()
    assert current["id"] == adopted["later"]["id"]
    assert current["parent_version_id"] == historical["id"]
    assert Path(current["file_path"]).exists()
    assert Path(before["file_path"]).exists()
    assert not candidate.exists()
    assert not later_candidate.exists()


def test_adoption_supersedes_prior_exports(checked_out_file, candidate, tmp_path):
    export_path = tmp_path / "ready-export.mrc"
    export_path.write_bytes(candidate.read_bytes())
    with db.connect() as conn:
        export_id = conn.execute(
            "INSERT INTO job_file_exports(job_file_id,version_id,purpose,description,"
            "filename,file_path,record_count,validation_json,state,created_by,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (
                checked_out_file["id"], checked_out_file["current_version_id"],
                "EDS deletion load", "", "ready-export.mrc", str(export_path),
                1, "{}", "ready", OWNER, "2026-07-15T12:00:00Z",
            ),
        ).fetchone()["id"]

    created = _adopt(checked_out_file, candidate)

    with db.connect() as conn:
        export = conn.execute(
            "SELECT state,superseded_at,superseded_by_version_id"
            " FROM job_file_exports WHERE id=?",
            (export_id,),
        ).fetchone()
    assert export["state"] == "superseded"
    assert export["superseded_at"] is not None
    assert export["superseded_by_version_id"] == created["id"]


def test_session_adopts_candidate_and_reopens_new_current(
    checked_out_file, candidate, monkeypatch,
):
    state = {
        "user": OWNER,
        "job_file_id": checked_out_file["id"],
        "job_file_version_id": checked_out_file["current_version_id"],
        "quick_batch_preview": SimpleNamespace(workdir=candidate.parent / "unused"),
    }
    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(session_state=state))
    monkeypatch.setattr(session, "current_user_id", lambda: OWNER)

    created = session.adopt_current_candidate(
        candidate_path=candidate,
        source_kind="quick-batch",
        label="Set leader status to deleted",
    )

    assert state["job_file_version_id"] == created["id"]
    assert state["store"].path == Path(created["file_path"])
    assert "quick_batch_preview" not in state


def test_session_rejects_candidate_without_job_file_context(candidate, monkeypatch):
    state = {"user": OWNER, "job_file_id": None, "job_file_version_id": None}
    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(session_state=state))

    with pytest.raises(
        job_files.JobFileError,
        match="This change requires a file opened from a job\\.",
    ):
        session.adopt_current_candidate(
            candidate_path=candidate,
            source_kind="quick-batch",
            label="Set leader status to deleted",
        )

    assert candidate.exists()
