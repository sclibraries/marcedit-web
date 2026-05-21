"""Round-trip tests: every record in the fixture must survive
parse → render → parse without losing data.

The contract is that `mrk_writer.render_record_mrk(rec)` followed by
`mrk_parser.parse_mrk(...)` returns a record whose `str(...)` matches
the original `str(...)`. This is the load-bearing guarantee for the
MarcEditor (Stage 10): save round-trips back to a byte-identical .mrc
when no edits were made.
"""

from __future__ import annotations

import io
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import mrk_parser, mrk_writer


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.mrc"


def _load_fixture_records() -> list[pymarc.Record]:
    with FIXTURE.open("rb") as f:
        reader = pymarc.MARCReader(f, to_unicode=True, permissive=True)
        return [r for r in reader if r is not None]


@pytest.fixture(scope="module")
def fixture_records():
    return _load_fixture_records()


def test_single_record_roundtrip(fixture_records):
    """Each record round-trips byte-exactly through render→parse."""
    for original in fixture_records:
        text = mrk_writer.render_record_mrk(original)
        parsed_records, file_errors = mrk_parser.parse_mrk(text)
        assert file_errors == []
        assert len(parsed_records) == 1
        assert parsed_records[0].record is not None
        assert parsed_records[0].errors == []
        # Byte-exact round-trip on the .mrk representation.
        assert str(parsed_records[0].record) == str(original), (
            f"round-trip mismatch for record with 001="
            f"{original.get('001').data if original.get('001') else 'N/A'}"
        )


def test_batch_roundtrip_preserves_record_count(fixture_records):
    text = mrk_writer.render_records_mrk(fixture_records)
    records, file_errors = mrk_parser.parse_mrk(text)
    assert file_errors == []
    assert len(records) == len(fixture_records)
    for i, (parsed, original) in enumerate(zip(records, fixture_records)):
        assert parsed.errors == [], f"errors on record {i}: {parsed.errors}"
        assert str(parsed.record) == str(original), (
            f"batch round-trip mismatch at index {i}"
        )


def test_idempotent_under_multiple_passes(fixture_records):
    """parse → render → parse → render yields the same text as one cycle."""
    original_text = mrk_writer.render_records_mrk(fixture_records)
    parsed, _ = mrk_parser.parse_mrk(original_text)
    once = mrk_writer.render_records_mrk(p.record for p in parsed if p.record)
    parsed2, _ = mrk_parser.parse_mrk(once)
    twice = mrk_writer.render_records_mrk(p.record for p in parsed2 if p.record)
    assert once == twice


def test_roundtrip_serializes_back_to_valid_mrc(fixture_records):
    """After parsing edited .mrk, MARCWriter must produce a readable .mrc."""
    text = mrk_writer.render_records_mrk(fixture_records)
    parsed, _ = mrk_parser.parse_mrk(text)

    buf = io.BytesIO()
    writer = pymarc.MARCWriter(buf)
    for p in parsed:
        assert p.record is not None
        writer.write(p.record)

    # Read back what we just wrote.
    raw = buf.getvalue()
    reread = list(pymarc.MARCReader(io.BytesIO(raw), to_unicode=True, permissive=True))
    assert len(reread) == len(fixture_records)
    # The 001 values are the easiest stable signal that round-trip works.
    assert [r.get("001").data for r in reread] == [
        r.get("001").data for r in fixture_records
    ]
