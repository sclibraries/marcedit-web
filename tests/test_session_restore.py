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


class _WidgetOwnedState(dict):
    """session_state stand-in where selected keys refuse writes.

    Mirrors real Streamlit: once a widget is instantiated with
    ``key=<name>``, any assignment to ``st.session_state[<name>]`` in the
    same script run raises — even an assignment of the identical value.
    """

    def __init__(self, *args, widget_keys=(), **kwargs):
        super().__init__(*args, **kwargs)
        self._widget_keys = set(widget_keys)

    def __setitem__(self, key, value):
        if key in self._widget_keys:
            raise RuntimeError(
                f"st.session_state.{key} cannot be modified after the "
                f"widget with key {key} is instantiated"
            )
        super().__setitem__(key, value)


def test_load_persisted_upload_tolerates_widget_owned_current_job_id(
    fake_st, record, tmp_path, monkeypatch,
):
    """Load from Home must not crash on the widget-owned job key (TASK-127).

    Home's Job selectbox is created with ``key="current_job_id"``, so by the
    time the table's Load button handler runs, that key is widget-owned and
    Streamlit forbids assigning to it. Home only lists the selected job's
    files, so the value would be unchanged anyway — the load must succeed
    without touching the key.
    """
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    st.session_state["current_job_id"] = job["id"]
    session.handle_upload(_FakeUpload("first.mrc", _serialize([record])))
    upload = upload_persistence.get_active_upload("alice@example.edu")

    st.session_state = _WidgetOwnedState(
        st.session_state, widget_keys={"current_job_id"}
    )

    summary = session.load_persisted_upload(upload["id"])

    assert summary["error"] is None
    assert st.session_state["current_job_id"] == job["id"]
    assert st.session_state["store"].filename == "first.mrc"


def test_load_persisted_upload_switches_job_when_key_is_free(
    fake_st, record, tmp_path, monkeypatch,
):
    """Loading another job's upload must still retarget the session (TASK-127).

    The Jobs page has no widget keyed ``current_job_id``, and its file list
    can span jobs other than the session's current one. Loading such an
    upload must keep updating ``current_job_id`` so later uploads and page
    logic attach to the right job.
    """
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    vendor_job = jobs.create_job("alice@example.edu", "Vendor load June")
    st.session_state["current_job_id"] = vendor_job["id"]
    session.handle_upload(_FakeUpload("vendor.mrc", _serialize([record])))
    upload = upload_persistence.get_active_upload("alice@example.edu")

    other_job = jobs.create_job("alice@example.edu", "Authority cleanup")
    st.session_state["current_job_id"] = other_job["id"]

    summary = session.load_persisted_upload(upload["id"])

    assert summary["error"] is None
    assert st.session_state["current_job_id"] == vendor_job["id"]


def test_detach_loaded_batch_clears_store_for_deleted_file(
    fake_st, record, tmp_path, monkeypatch,
):
    """Hard-deleting the loaded upload must drop the session batch (TASK-128).

    ``jobs.remove_upload(delete_file=True)`` unlinks the backing file; if
    the store stays attached, the next disk read (e.g. Home's Loaded batch
    download) crashes with FileNotFoundError.
    """
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("vendor.mrc", _serialize([record])))
    upload = upload_persistence.get_active_upload("alice@example.edu")
    st.session_state["editor_text"] = "007 stale"
    st.session_state["editor_dirty"] = True

    jobs.remove_upload(upload["id"], by="alice@example.edu", delete_file=True)
    session.detach_loaded_batch(upload["file_path"])

    assert st.session_state["store"] is None
    assert st.session_state["issues_cache"] == {}
    assert st.session_state["editor_text"] is None
    assert st.session_state["editor_dirty"] is False


def test_detach_loaded_batch_ignores_other_files(
    fake_st, record, tmp_path, monkeypatch,
):
    """Deleting an upload that is NOT loaded must leave the batch alone."""
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("first.mrc", _serialize([record])))
    first = upload_persistence.get_active_upload("alice@example.edu")
    session.handle_upload(_FakeUpload("second.mrc", _serialize([record, record])))
    loaded_store = st.session_state["store"]

    jobs.remove_upload(first["id"], by="alice@example.edu", delete_file=True)
    session.detach_loaded_batch(first["file_path"])

    assert st.session_state["store"] is loaded_store


def test_current_raw_bytes_returns_none_when_backing_file_missing(
    fake_st, record, tmp_path, monkeypatch,
):
    """A dangling store must degrade to no-download, not a crash (TASK-128).

    The deleter's own session is detached explicitly, but a collaborator's
    session can still hold a store whose file another user deleted.
    """
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = fake_st()
    st.session_state["user"] = "alice@example.edu"
    session.handle_upload(_FakeUpload("vendor.mrc", _serialize([record])))
    Path(st.session_state["store"].path).unlink()

    assert session.current_raw_bytes() is None


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
