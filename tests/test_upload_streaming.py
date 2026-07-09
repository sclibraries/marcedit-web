"""handle_upload must stream uploads to disk, not materialize them (TASK-132).

The uploader widget already holds one full copy of the file in server
RAM; a second ``.getvalue()`` copy in the ingest path doubled the peak.
That memory pattern is implicated in the TASK-117 overnight outage, so
this test encodes the constraint directly: ingest succeeds while the
upload object refuses whole-body reads.

Fake-Streamlit pattern mirrors ``tests/test_session_restore.py``.
"""

from __future__ import annotations

import io
import sys
import types

import pymarc
import pytest

from marcedit_web.lib import db, session


class _FakeSt:
    def __init__(self):
        self.session_state: dict = {}
        self.runtime = types.SimpleNamespace(
            scriptrunner=types.SimpleNamespace(
                get_script_run_ctx=lambda: None
            )
        )


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def _serialize(records):
    out = io.BytesIO()
    writer = pymarc.MARCWriter(out)
    for r in records:
        writer.write(r)
    return out.getvalue()


class _StreamOnlyUpload(io.BytesIO):
    """UploadedFile stand-in that forbids whole-body materialization."""

    def __init__(self, name: str, data: bytes):
        super().__init__(data)
        self.name = name
        self.size = len(data)

    def getvalue(self) -> bytes:
        raise AssertionError("handle_upload must not materialize the upload")

    def read(self, size=-1):
        assert size is not None and size > 0, (
            f"unbounded read({size}) materializes the whole upload"
        )
        return super().read(size)


def test_handle_upload_streams_without_materializing(
    record, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "u"))
    st = _FakeSt()
    monkeypatch.setitem(sys.modules, "streamlit", st)
    st.session_state["user"] = "alice@example.edu"

    summary = session.handle_upload(
        _StreamOnlyUpload("batch.mrc", _serialize([record]))
    )

    assert summary.get("error") is None
    assert summary["total"] == 1
    store = st.session_state["store"]
    assert store.count() == 1
    first = store.get(0)
    assert first is not None
    assert first.get("001").data == "1234567890"
