"""Tests for marcedit_web.lib.session — the pure RecordStore-backed surface.

Streamlit-flavored helpers (`init`, `handle_upload`, etc.) are exercised
end-to-end by the Playwright smoke; here we cover the in-memory
RecordStore round-trip + state-shape contract.
"""

from __future__ import annotations

import io
from pathlib import Path

import pymarc

from marcedit_web.lib import session
from marcedit_web.lib.record_store import RecordStore


def _serialize(records):
    out = io.BytesIO()
    writer = pymarc.MARCWriter(out)
    for r in records:
        writer.write(r)
    return out.getvalue()


def test_record_store_from_bytes_empty_yields_zero_count(tmp_path):
    s = RecordStore.from_bytes(b"", tmp_dir=tmp_path / "empty")
    assert s.count() == 0
    assert s.malformed_count() == 0


def test_record_store_from_bytes_decodes_one_record(record, tmp_path):
    data = _serialize([record])
    s = RecordStore.from_bytes(data, tmp_dir=tmp_path / "one")
    assert s.count() == 1
    first = s.get(0)
    assert first is not None
    assert first.get("001").data == "1234567890"


def test_record_store_from_bytes_decodes_multiple(make_record, tmp_path):
    data = _serialize([make_record(), make_record(), make_record()])
    s = RecordStore.from_bytes(data, tmp_dir=tmp_path / "many")
    assert s.count() == 3


def test_record_store_handles_garbage_without_raising(tmp_path):
    # Pure garbage that doesn't even start with a leader-shaped prefix.
    s = RecordStore.from_bytes(
        b"\x00\x00\x00not-a-record", tmp_dir=tmp_path / "garbage",
    )
    # Either we got 0 records or some malformed counter — the only
    # contract is "does not raise".
    assert s.count() >= 0


def test_state_defaults_shape():
    keys = set(session.STATE_DEFAULTS)
    expected = {
        "user",
        "store",
        "issues_cache",
        "editor_text",
        "editor_dirty",
        "tasks_palette_state",
    }
    assert expected.issubset(keys)


def test_v1_records_key_is_gone():
    """The v1 `records: list[Record]` key was replaced by `store`."""
    assert "records" not in session.STATE_DEFAULTS
    assert "raw_bytes" not in session.STATE_DEFAULTS
    assert "malformed_count" not in session.STATE_DEFAULTS


def test_stamped_filename_shape():
    """TASK-078c: single owner of the download-filename timestamp shape."""
    import re

    assert re.fullmatch(
        r"records_\d{8}_\d{6}\.mrk", session.stamped_filename("records", ".mrk")
    )
    # default suffix is .mrc
    assert re.fullmatch(
        r"matches_\d{8}_\d{6}\.mrc", session.stamped_filename("matches")
    )


def test_stamped_filename_exact_format(monkeypatch):
    """Pin the exact historical name (not just shape) at a fixed instant."""
    import datetime as _dt

    class _FixedDT:
        @staticmethod
        def now():
            return _dt.datetime(2026, 6, 18, 14, 30, 5)

    monkeypatch.setattr(session, "datetime", _FixedDT)
    assert session.stamped_filename("records", ".mrk") == "records_20260618_143005.mrk"
    assert session.stamped_filename("matches") == "matches_20260618_143005.mrc"
    assert session.stamped_filename("x_deletes") == "x_deletes_20260618_143005.mrc"


def _fake_streamlit(monkeypatch, session_state):
    import sys
    import types

    monkeypatch.setitem(
        sys.modules, "streamlit", types.SimpleNamespace(session_state=session_state)
    )


def test_current_user_id_returns_cached_value(monkeypatch):
    """TASK-078b: the single identity read-point returns the cached value."""
    _fake_streamlit(monkeypatch, {"user": "alice@smith.edu"})
    assert session.current_user_id() == "alice@smith.edu"


def test_current_user_id_anonymous_when_unset(monkeypatch):
    _fake_streamlit(monkeypatch, {})
    assert session.current_user_id() == "anonymous"


def test_current_user_id_anonymous_when_empty(monkeypatch):
    _fake_streamlit(monkeypatch, {"user": ""})
    assert session.current_user_id() == "anonymous"
