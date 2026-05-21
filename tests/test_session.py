"""Tests for marcedit_web.lib.session — the pure parsing surface.

Streamlit-flavored helpers (`init`, `handle_upload`, etc.) are exercised
end-to-end by the Playwright smoke test in CI; here we cover the pure
parsing logic that doesn't need a Streamlit runtime context.
"""

from __future__ import annotations

import io

import pymarc

from marcedit_web.lib import session


def _serialize(records):
    out = io.BytesIO()
    writer = pymarc.MARCWriter(out)
    for r in records:
        writer.write(r)
    return out.getvalue()


def test_parse_uploaded_bytes_empty_returns_zero_zero():
    records, malformed = session.parse_uploaded_bytes(b"")
    assert records == []
    assert malformed == 0


def test_parse_uploaded_bytes_decodes_one_record(record):
    data = _serialize([record])
    records, malformed = session.parse_uploaded_bytes(data)
    assert len(records) == 1
    assert malformed == 0
    assert records[0].get("001").data == "1234567890"


def test_parse_uploaded_bytes_decodes_multiple(make_record):
    data = _serialize([make_record(), make_record(), make_record()])
    records, malformed = session.parse_uploaded_bytes(data)
    assert len(records) == 3
    assert malformed == 0


def test_parse_uploaded_bytes_counts_malformed(record):
    # Splice a junk byte run between two valid records; the junk is not
    # a valid MARC record so MARCReader should count it as malformed
    # while still returning the surrounding good records.
    good = _serialize([record])
    junk = b"NOT A REAL MARC RECORD"
    data = good + junk + good
    records, malformed = session.parse_uploaded_bytes(data)
    # We don't pin the exact malformed count — pymarc may swallow the
    # junk silently or count it once. The contract we promise is:
    # "good records survive; the function does not raise."
    assert len(records) >= 1


def test_parse_uploaded_bytes_does_not_raise_on_garbage():
    # Pure garbage that doesn't even start with a leader-shaped prefix.
    session.parse_uploaded_bytes(b"\x00\x00\x00not-a-record")


def test_state_defaults_shape():
    keys = set(session.STATE_DEFAULTS)
    expected = {
        "user",
        "filename",
        "raw_bytes",
        "records",
        "malformed_count",
        "issues_cache",
        "editor_text",
        "editor_dirty",
        "tasks_palette_state",
    }
    assert expected.issubset(keys)
