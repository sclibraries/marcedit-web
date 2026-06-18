"""Tests for marcedit_web.lib.reporting."""

from __future__ import annotations

import pymarc

from marcedit_web.lib import reporting


def test_leader_format_label_known():
    assert reporting._leader_format_label("a", "m") == "book"
    assert reporting._leader_format_label("a", "s") == "serial"
    assert reporting._leader_format_label("a", "i") == "database"
    assert reporting._leader_format_label("g", "m") == "video"


def test_leader_format_label_unknown():
    assert reporting._leader_format_label("z", "z") == "unknown"


def test_record_snapshot_of(record):
    snap = reporting.RecordSnapshot.of(record, index=1)
    assert snap.index == 1
    assert snap.identifier == "1234567890"
    assert snap.title == "Test title"
    assert snap.format_label == "book"
    assert snap.tags_present["856"] == 2
    assert snap.tags_present["245"] == 1
    assert "example.org" in snap.url_domains


def test_domain_from_url_strips_to_host():
    assert reporting._domain_from_url("https://example.org/foo") == "example.org"
    assert reporting._domain_from_url("") is None


def test_run_summary_accumulates(record):
    summary = reporting.RunSummary()
    before = reporting.RecordSnapshot.of(record, index=1)
    after = reporting.RecordSnapshot.of(record, index=1)
    rr = reporting.RecordReport(before=before, after=after)
    summary.record(rr)
    assert summary.total == 1
    assert summary.ok == 1
    assert summary.formats["book"] == 1
    assert summary.tag_counts["856"] == 2


def test_smith_specific_helpers_are_gone():
    for name in ("_container_from_035", "check_warnings"):
        assert not hasattr(reporting, name)


def _record_with_035a(value):
    rec = pymarc.Record()
    rec.add_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", value)],
        )
    )
    return rec


def test_snapshot_oclc_number_from_oclc_035():
    snap = reporting.RecordSnapshot.of(_record_with_035a("(OCoLC)12345"), index=0)
    assert snap.oclc_number == "12345"


def test_snapshot_oclc_number_tolerates_leading_space():
    """TASK-078a: a leading space before (OCoLC) no longer defeats extraction."""
    snap = reporting.RecordSnapshot.of(_record_with_035a("  (OCoLC)12345"), index=0)
    assert snap.oclc_number == "12345"


def test_snapshot_oclc_number_none_for_bare_number():
    snap = reporting.RecordSnapshot.of(_record_with_035a("12345"), index=0)
    assert snap.oclc_number is None
