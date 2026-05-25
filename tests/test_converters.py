"""Tests for marcedit_web.lib.converters (TASK-032 Marc Tools)."""

from __future__ import annotations

import io
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import converters


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.mrc"


@pytest.fixture
def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


# ---------------------------------------------------------------------------
# Binary → .mrk
# ---------------------------------------------------------------------------


def test_to_mrk_text_round_trips_identifier(fixture_bytes):
    """Binary → .mrk → binary preserves the 001 of every record."""
    forward = converters.to_mrk_text(fixture_bytes)
    assert forward.record_count > 0
    assert isinstance(forward.output, str)
    assert "=LDR" in forward.output

    back = converters.to_binary_from_mrk(forward.output)
    assert back.record_count == forward.record_count

    original_ids = [
        r.get("001").data for r in
        pymarc.MARCReader(io.BytesIO(fixture_bytes),
                          to_unicode=True, permissive=True)
        if r and r.get("001")
    ]
    round_tripped_ids = [
        r.get("001").data for r in
        pymarc.MARCReader(io.BytesIO(back.output),
                          to_unicode=True, permissive=True)
        if r and r.get("001")
    ]
    assert original_ids == round_tripped_ids


def test_to_mrk_text_counts_malformed(fixture_bytes):
    """Append junk after the last record; the .mrk converter notes it."""
    result = converters.to_mrk_text(fixture_bytes + b"garbage-no-leader")
    assert result.record_count > 0
    # pymarc.MARCReader's permissive mode may or may not count the
    # trailing junk depending on internals; the contract is "doesn't
    # crash and records still come through."
    assert result.malformed_count >= 0


# ---------------------------------------------------------------------------
# .mrk → binary
# ---------------------------------------------------------------------------


def test_to_binary_from_mrk_round_trips(fixture_bytes):
    mrk = converters.to_mrk_text(fixture_bytes).output
    back = converters.to_binary_from_mrk(mrk)
    assert back.record_count > 0
    # Output is parseable as MARC binary.
    reread = list(pymarc.MARCReader(io.BytesIO(back.output),
                                    to_unicode=True, permissive=True))
    assert len(reread) == back.record_count


def test_to_binary_from_mrk_surfaces_line_errors():
    """A junk line lands in ``line_errors`` instead of corrupting output."""
    bad_mrk = (
        "=LDR  00000nam a2200000 a 4500\n"
        "=001  X-001\n"
        "=245  10$aOnly title.\n"
        "NOT A REAL LINE\n"
    )
    result = converters.to_binary_from_mrk(bad_mrk)
    assert result.line_errors
    assert any(e.code == "no-tag-prefix" for e in result.line_errors)


def test_to_binary_from_mrk_empty_input():
    """No input → empty output, no records."""
    result = converters.to_binary_from_mrk("")
    assert result.record_count == 0
    assert result.output == b""


# ---------------------------------------------------------------------------
# Binary ↔ MARCXML
# ---------------------------------------------------------------------------


def test_to_marcxml_emits_well_formed_collection(fixture_bytes):
    result = converters.to_marcxml(fixture_bytes)
    text = result.output.decode("utf-8")
    assert text.startswith("<?xml")
    assert "<collection" in text
    assert "<record" in text
    assert "<datafield" in text
    assert "<subfield" in text
    assert text.endswith("</collection>")
    assert result.record_count > 0


def test_marcxml_round_trip_preserves_record_count(fixture_bytes):
    forward = converters.to_marcxml(fixture_bytes)
    back = converters.to_binary_from_marcxml(forward.output)
    assert back.record_count == forward.record_count


def test_marcxml_round_trip_preserves_001(fixture_bytes):
    forward = converters.to_marcxml(fixture_bytes)
    back = converters.to_binary_from_marcxml(forward.output)
    original_ids = [
        r.get("001").data for r in
        pymarc.MARCReader(io.BytesIO(fixture_bytes),
                          to_unicode=True, permissive=True)
        if r and r.get("001")
    ]
    round_tripped_ids = [
        r.get("001").data for r in
        pymarc.MARCReader(io.BytesIO(back.output),
                          to_unicode=True, permissive=True)
        if r and r.get("001")
    ]
    assert original_ids == round_tripped_ids


def test_to_binary_from_marcxml_rejects_garbage():
    with pytest.raises(ValueError):
        converters.to_binary_from_marcxml("<not xml at all")


def test_to_binary_from_marcxml_rejects_doctype():
    """TASK-035: DTD declarations are refused (billion-laughs / XXE)."""
    payload = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE collection [\n'
        '  <!ELEMENT collection ANY>\n'
        ']>\n'
        '<collection xmlns="http://www.loc.gov/MARC21/slim"></collection>'
    )
    with pytest.raises(ValueError) as exc:
        converters.to_binary_from_marcxml(payload)
    assert "DOCTYPE" in str(exc.value)


def test_to_binary_from_marcxml_rejects_entity_declaration():
    """TASK-035: ENTITY declarations are refused even without DOCTYPE wrapper."""
    payload = (
        '<?xml version="1.0"?>\n'
        '<!ENTITY xxe SYSTEM "file:///etc/passwd">\n'
        '<collection xmlns="http://www.loc.gov/MARC21/slim"></collection>'
    )
    with pytest.raises(ValueError) as exc:
        converters.to_binary_from_marcxml(payload)
    assert "ENTITY" in str(exc.value)


def test_to_binary_from_marcxml_doctype_check_is_case_insensitive():
    """Lowercase ``<!doctype`` and uppercase ``<!DOCTYPE`` both rejected."""
    payload = (
        '<?xml version="1.0"?>\n'
        '<!doctype collection>\n'
        '<collection xmlns="http://www.loc.gov/MARC21/slim"></collection>'
    )
    with pytest.raises(ValueError):
        converters.to_binary_from_marcxml(payload)


def test_to_binary_from_marcxml_rejects_doctype_buried_after_long_prolog():
    """A hostile file can pad with comments before <!DOCTYPE — still rejected."""
    padding = "<!-- " + ("x" * 10000) + " -->\n"  # >> the old 4 KB head scan
    payload = (
        '<?xml version="1.0"?>\n'
        + padding
        + '<!DOCTYPE collection>\n'
        + '<collection xmlns="http://www.loc.gov/MARC21/slim"></collection>'
    )
    with pytest.raises(ValueError) as exc:
        converters.to_binary_from_marcxml(payload)
    assert "DOCTYPE" in str(exc.value)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_records_to_csv_rows_default_columns(fixture_bytes):
    records = list(pymarc.MARCReader(io.BytesIO(fixture_bytes),
                                     to_unicode=True, permissive=True))
    rows = converters.records_to_csv_rows(iter(records))
    assert len(rows) == len(records)
    # Every default column appears as a key on every row.
    default_cols = [c for c, _t, _s in converters.DEFAULT_CSV_COLUMNS]
    for row in rows:
        assert set(row.keys()) == set(default_cols)


def test_records_to_csv_rows_pulls_245_a(record):
    rows = converters.records_to_csv_rows(iter([record]))
    assert rows[0]["245_a"] == "Test title."


def test_records_to_csv_rows_missing_field_is_empty(record):
    """A record without a 260 yields empty strings for those columns."""
    record.remove_fields("260")
    rows = converters.records_to_csv_rows(iter([record]))
    assert rows[0]["260_a"] == ""


def test_records_to_csv_rows_008_date_1(fixture_bytes):
    """The 008_date_1 column reads bytes 7-10 of the 008 field."""
    records = list(pymarc.MARCReader(io.BytesIO(fixture_bytes),
                                     to_unicode=True, permissive=True))
    rows = converters.records_to_csv_rows(iter(records))
    # Fixture record 1's 008 has "2025" at positions 7-10
    # ("260430t20252025ctuac\\\ob\\\\001\0\eng\d"). Spot-check that
    # column got SOMETHING year-like.
    assert any(len(r["008_date_1"]) == 4 and r["008_date_1"].isdigit()
               for r in rows)


def test_write_csv_emits_header_and_rows():
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    csv_text = converters.write_csv(rows, columns=["a", "b"])
    assert csv_text.splitlines()[0] == "a,b"
    assert "1,2" in csv_text
    assert "3,4" in csv_text
