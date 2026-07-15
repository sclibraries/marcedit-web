"""Authoritative session context for TASK-151 job-file work items."""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pymarc
import pytest

from marcedit_web.lib import db, job_files, jobs, session, upload_persistence


class _FakeStreamlit:
    def __init__(self, state=None):
        self.session_state = state or {}
        self.toasts = []

    def toast(self, message, icon=None):
        self.toasts.append((message, icon))


@pytest.fixture(autouse=True)
def _job_files_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))


def _marc_bytes(record) -> bytes:
    target = io.BytesIO()
    writer = pymarc.MARCWriter(target)
    writer.write(record)
    return target.getvalue()


@pytest.fixture
def attached_file(tmp_path, record):
    raw = _marc_bytes(record)
    source = tmp_path / "deletes.mrc"
    source.write_bytes(raw)
    job = jobs.create_job("owner@example.edu", "Routledge")
    return job_files.attach_file(
        job_id=job["id"],
        user_email="owner@example.edu",
        source_path=source,
        filename="deletes.mrc",
        record_count=1,
        file_bytes=len(raw),
    )


def test_open_job_file_records_exact_context(monkeypatch, attached_file):
    fake_st = _FakeStreamlit({"user": "owner@example.edu"})
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(session, "current_user_id", lambda: "owner@example.edu")

    summary = session.open_job_file(attached_file["id"])

    assert summary["id"] == attached_file["id"]
    assert summary["job_file_version_id"] == attached_file["current_version_id"]
    assert fake_st.session_state["job_file_id"] == attached_file["id"]
    assert (
        fake_st.session_state["job_file_version_id"]
        == attached_file["current_version_id"]
    )
    assert fake_st.session_state["current_job_id"] == attached_file["job_id"]
    assert fake_st.session_state["store"].filename == "deletes.mrc"


def test_init_restores_exact_job_file_after_refresh(monkeypatch, attached_file):
    """Refresh must re-query file access/version, not infer identity from uploads."""
    fake_st = _FakeStreamlit(
        {
            "user": "owner@example.edu",
            "job_file_id": attached_file["id"],
            "job_file_version_id": attached_file["current_version_id"],
        }
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    session.init()

    assert fake_st.session_state["job_file_id"] == attached_file["id"]
    assert (
        fake_st.session_state["job_file_version_id"]
        == attached_file["current_version_id"]
    )
    assert fake_st.session_state["store"].filename == "deletes.mrc"


def test_current_job_file_clears_inaccessible_cached_context(
    monkeypatch, attached_file,
):
    fake_st = _FakeStreamlit(
        {
            "user": "outsider@example.edu",
            "job_file_id": attached_file["id"],
            "job_file_version_id": attached_file["current_version_id"],
            "store": object(),
        }
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(session, "current_user_id", lambda: "outsider@example.edu")

    assert session.current_job_file() is None
    assert fake_st.session_state["job_file_id"] is None
    assert fake_st.session_state["job_file_version_id"] is None
    assert fake_st.session_state["store"] is None


def test_inaccessible_job_file_context_does_not_fall_back_to_legacy_upload(
    monkeypatch, attached_file, tmp_path,
):
    """A revoked file id must fail closed instead of restoring unrelated bytes."""
    legacy_path = tmp_path / "legacy.mrc"
    legacy_path.write_bytes(
        Path(job_files.get_current_version(
            attached_file["id"], "owner@example.edu"
        )["file_path"]).read_bytes()
    )
    upload_persistence.record_upload(
        user="outsider@example.edu",
        filename="legacy.mrc",
        file_path=legacy_path,
        record_count=1,
        file_bytes=legacy_path.stat().st_size,
    )
    fake_st = _FakeStreamlit(
        {
            "user": "outsider@example.edu",
            "job_file_id": attached_file["id"],
            "job_file_version_id": attached_file["current_version_id"],
        }
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    session.init()

    assert fake_st.session_state["store"] is None
    assert fake_st.session_state["job_file_id"] is None


def test_refresh_adopts_new_current_version_and_clears_mutation_previews(
    monkeypatch, attached_file, tmp_path,
):
    """A cross-cataloger update must replace every cache tied to old bytes."""
    old_version = job_files.get_current_version(
        attached_file["id"], "owner@example.edu"
    )
    new_path = tmp_path / "v000002.mrc"
    shutil.copyfile(old_version["file_path"], new_path)
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO job_file_versions(job_file_id,version_number,"
            "parent_version_id,file_path,record_count,file_bytes,source_kind,"
            "label,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                attached_file["id"],
                2,
                old_version["id"],
                str(new_path),
                1,
                new_path.stat().st_size,
                "task",
                "Peer update",
                "owner@example.edu",
                "2026-07-14T20:00:00Z",
            ),
        )
        new_version_id = int(cursor.lastrowid)
        conn.execute(
            "UPDATE job_files SET current_version_id=? WHERE id=?",
            (new_version_id, attached_file["id"]),
        )
    quick_dir = tmp_path / "quick-preview"
    replace_dir = tmp_path / "replace-preview"
    quick_dir.mkdir()
    replace_dir.mkdir()
    fake_st = _FakeStreamlit(
        {
            "user": "owner@example.edu",
            "store": object(),
            "job_file_id": attached_file["id"],
            "job_file_version_id": old_version["id"],
            "quick_batch_preview": SimpleNamespace(workdir=quick_dir),
            "batch_replace_preview": SimpleNamespace(sandbox_workdir=replace_dir),
            "folio_safe_fix_preview": object(),
        }
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    session.init()

    assert fake_st.session_state["job_file_version_id"] == new_version_id
    assert fake_st.session_state["store"].path == new_path
    assert not quick_dir.exists()
    assert not replace_dir.exists()
    assert "folio_safe_fix_preview" not in fake_st.session_state
