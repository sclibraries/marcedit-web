"""Tests for session.restore_active_upload + handle_upload persistence
(TASK-051).

Uses a fake Streamlit module so we can exercise the session helpers
without booting Streamlit, mirroring the pattern in
``tests/test_session_enforce.py``.
"""

from __future__ import annotations

import io
import sys
import types
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import db, jobs, session, upload_persistence
from marcedit_web.lib.record_store import RecordStore


class _FakeSt:
    """Minimal Streamlit stand-in for restore + handle_upload tests."""

    def __init__(self):
        self.session_state: dict = {}
        self.runtime = types.SimpleNamespace(
            scriptrunner=types.SimpleNamespace(
                get_script_run_ctx=lambda: None
            )
        )


@pytest.fixture
def fake_st(monkeypatch):
    def _install():
        fake = _FakeSt()
        monkeypatch.setitem(sys.modules, "streamlit", fake)
        return fake

    return _install


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def _serialize(records):
    out = io.BytesIO()
    writer = pymarc.MARCWriter(out)
    for r in records:
        writer.write(r)
    return out.getvalue()


class _FakeUpload:
    """Stand-in for whatever Streamlit's file_uploader returns."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


# ---------------------------------------------------------------------------
# handle_upload — persists for OAuth, not for anonymous
# ---------------------------------------------------------------------------


def test_handle_upload_writes_persisted_row_for_oauth_user(
    fake_st, record, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"

    upload = _FakeUpload("test.mrc", _serialize([record]))
    summary = session.handle_upload(upload)

    assert summary["total"] == 1
    row = upload_persistence.get_active_upload("alice@example.edu")
    assert row is not None
    assert row["filename"] == "test.mrc"
    assert row["record_count"] == 1
    assert Path(row["file_path"]).exists()


def test_handle_upload_no_row_for_anonymous_user(fake_st, record, tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "anonymous"

    upload = _FakeUpload("test.mrc", _serialize([record]))
    session.handle_upload(upload)

    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
    assert n == 0


def test_handle_upload_clear_removes_persisted_row(fake_st, record, tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("test.mrc", _serialize([record])))
    assert upload_persistence.get_active_upload("alice@example.edu") is not None

    # Now clear by passing None (the file_uploader-returns-None case).
    session.handle_upload(None)
    assert upload_persistence.get_active_upload("alice@example.edu") is None


def test_handle_upload_re_upload_replaces_active_row(
    fake_st, record, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"

    session.handle_upload(_FakeUpload("first.mrc", _serialize([record])))
    first = upload_persistence.get_active_upload("alice@example.edu")

    session.handle_upload(_FakeUpload("second.mrc", _serialize([record, record])))
    second = upload_persistence.get_active_upload("alice@example.edu")

    assert first["filename"] == "first.mrc"
    assert second["filename"] == "second.mrc"
    assert second["record_count"] == 2


def test_handle_upload_keeps_each_signed_in_upload_on_disk(
    fake_st, record, tmp_path, monkeypatch,
):
    """Job history needs each upload row to point at its own real file."""
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    st.session_state["current_job_id"] = job["id"]

    session.handle_upload(_FakeUpload("first.mrc", _serialize([record])))
    first = upload_persistence.get_active_upload("alice@example.edu")
    first_path = Path(first["file_path"])

    session.handle_upload(_FakeUpload("second.mrc", _serialize([record, record])))
    second = upload_persistence.get_active_upload("alice@example.edu")
    second_path = Path(second["file_path"])

    assert first_path != second_path
    assert first_path.exists()
    assert second_path.exists()
    assert first_path.read_bytes() == _serialize([record])
    assert second_path.read_bytes() == _serialize([record, record])


def test_handle_upload_attaches_to_selected_job(
    fake_st, record, tmp_path, monkeypatch,
):
    """Home's selected job should determine where the upload is attached."""
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    st.session_state["current_job_id"] = job["id"]

    session.handle_upload(_FakeUpload("test.mrc", _serialize([record])))

    row = upload_persistence.get_active_upload("alice@example.edu")
    assert row["job_id"] == job["id"]


def test_load_persisted_upload_reattaches_exact_job_file(
    fake_st, record, tmp_path, monkeypatch,
):
    """Catalogers need to switch back to a specific durable job upload."""
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    st.session_state["current_job_id"] = job["id"]

    first_bytes = _serialize([record])
    second_bytes = _serialize([record, record])
    session.handle_upload(_FakeUpload("first.mrc", first_bytes))
    first = upload_persistence.get_active_upload("alice@example.edu")
    session.handle_upload(_FakeUpload("second.mrc", second_bytes))

    summary = session.load_persisted_upload(first["id"])

    store = st.session_state["store"]
    assert summary == {
        "filename": "first.mrc",
        "total": 1,
        "malformed": 0,
        "error": None,
    }
    assert store.filename == "first.mrc"
    assert store.path.read_bytes() == first_bytes
    assert upload_persistence.get_active_upload("alice@example.edu")["id"] == first["id"]


# ---------------------------------------------------------------------------
# restore_active_upload — refresh-resume
# ---------------------------------------------------------------------------


def test_restore_active_upload_reattaches_existing_store(
    fake_st, record, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    # Step 1: real upload, populates DB + on-disk file.
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("test.mrc", _serialize([record])))

    # Step 2: simulate browser refresh — fresh session_state, same user.
    st.session_state.clear()
    st.session_state["user"] = "alice@example.edu"
    session.restore_active_upload()

    store = st.session_state.get("store")
    assert store is not None
    assert store.count() == 1
    assert store.filename == "test.mrc"


def test_restore_active_upload_no_op_for_anonymous(fake_st):
    st = fake_st()
    st.session_state["user"] = "anonymous"
    session.restore_active_upload()
    assert st.session_state.get("store") is None


def test_restore_active_upload_no_op_when_store_already_present(
    fake_st, record, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("first.mrc", _serialize([record])))
    held = st.session_state["store"]

    session.restore_active_upload()
    # Never clobber an in-flight store with a SQL-restored one.
    assert st.session_state["store"] is held


def test_restore_active_upload_clears_row_when_file_vanished(
    fake_st, record, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("test.mrc", _serialize([record])))

    # Simulate a /tmp sweep that took the on-disk file.
    row = upload_persistence.get_active_upload("alice@example.edu")
    Path(row["file_path"]).unlink()

    # Fresh session, refresh-resume attempt.
    st.session_state.clear()
    st.session_state["user"] = "alice@example.edu"
    session.restore_active_upload()

    assert st.session_state.get("store") is None
    # Row got flipped to inactive so we don't loop on it next time.
    assert upload_persistence.get_active_upload("alice@example.edu") is None


def test_restore_active_upload_audits_event(
    fake_st, record, tmp_path, monkeypatch,
):
    """A successful restore emits exactly one audit event."""
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("test.mrc", _serialize([record])))

    st.session_state.clear()
    st.session_state["user"] = "alice@example.edu"
    session.restore_active_upload()

    with db.connect() as conn:
        kinds = [
            r["kind"] for r in conn.execute(
                "SELECT kind FROM audit_events ORDER BY id"
            )
        ]
    assert "upload-restored" in kinds
