"""Tests for marcedit_web.lib.preflight (generic checks only, post-Smith strip)."""

from __future__ import annotations

import io
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import preflight
from marcedit_web.lib.errors import Issue


def _serialize(records):
    out = io.BytesIO()
    writer = pymarc.MARCWriter(out)
    for r in records:
        writer.write(r)
    return out.getvalue()


def test_run_preflight_with_records_returns_record_count_info(record):
    issues = preflight.run_preflight(records=[record], malformed=0)
    info = [i for i in issues if i.code == "record-count"]
    assert len(info) == 1
    assert info[0].severity == "info"
    assert "1" in info[0].message


def test_run_preflight_flags_missing_001(make_record):
    record = make_record()
    record.remove_fields("001")
    issues = preflight.run_preflight(records=[record])
    codes = {i.code for i in issues}
    assert "missing-001" in codes


def test_run_preflight_flags_missing_245(make_record):
    record = make_record()
    record.remove_fields("245")
    issues = preflight.run_preflight(records=[record])
    codes = {i.code for i in issues}
    assert "missing-245" in codes


def test_run_preflight_flags_missing_856(make_record):
    record = make_record()
    record.remove_fields("856")
    issues = preflight.run_preflight(records=[record])
    codes = {i.code for i in issues}
    assert "missing-856" in codes


def test_run_preflight_flags_empty_856_u(make_record):
    record = make_record()
    record.remove_fields("856")
    record.add_field(
        pymarc.Field(
            tag="856",
            indicators=["4", "0"],
            subfields=[pymarc.Subfield("u", "")],
        )
    )
    issues = preflight.run_preflight(records=[record])
    codes = {i.code for i in issues}
    assert "empty-856-u" in codes


def test_run_preflight_flags_duplicate_001(make_record):
    a = make_record()
    b = make_record()  # same 001
    issues = preflight.run_preflight(records=[a, b])
    codes = [i.code for i in issues]
    assert codes.count("duplicate-001") == 1


def test_run_preflight_malformed_count(make_record):
    issues = preflight.run_preflight(records=[make_record()], malformed=2)
    codes = {i.code for i in issues}
    assert "malformed-records" in codes


def test_run_preflight_expected_count_mismatch(make_record):
    issues = preflight.run_preflight(records=[make_record()], expected_count=5)
    codes = {i.code for i in issues}
    assert "record-count-mismatch" in codes


def test_run_preflight_no_records_no_path_returns_empty():
    assert preflight.run_preflight() == []


def test_run_preflight_no_records_with_path_returns_error(tmp_path):
    p = tmp_path / "missing.mrc"
    issues = preflight.run_preflight(p)
    assert issues[0].code == "input-missing"


def test_run_preflight_empty_file(tmp_path):
    p = tmp_path / "empty.mrc"
    p.write_bytes(b"")
    issues = preflight.run_preflight(p)
    assert issues[0].code == "input-empty"


def test_run_preflight_reads_real_mrc(tmp_path, record):
    p = tmp_path / "tiny.mrc"
    p.write_bytes(_serialize([record]))
    issues = preflight.run_preflight(p)
    assert any(i.code == "record-count" for i in issues)


def test_summarize_counts_by_severity():
    issues = [
        Issue(severity="error", scope="file", code="x", message="m"),
        Issue(severity="warning", scope="file", code="y", message="m"),
        Issue(severity="warning", scope="record", code="z", message="m"),
        Issue(severity="info", scope="file", code="i", message="m"),
    ]
    counts = preflight.summarize(issues)
    assert counts == {"error": 1, "warning": 2, "info": 1}


def test_has_blocking_errors():
    error = Issue(severity="error", scope="file", code="x", message="m")
    warning = Issue(severity="warning", scope="file", code="y", message="m")
    assert preflight.has_blocking_errors([error])
    assert not preflight.has_blocking_errors([warning])
    assert preflight.has_blocking_errors([warning], strict=True)


def test_smith_specific_preflight_helpers_are_gone():
    for name in (
        "_EDS_OPERATION_RE",
        "_CONTAINER_CODE_RE",
        "_RDA_REQUIRED_SOURCES",
        "_has_smith_035_9",
        "_eds_rda_issue",
        "_eds_filename_operation_issue",
        "_eds_filename_operation_missing_issue",
    ):
        assert not hasattr(preflight, name), f"{name} should be gone"


# ---------------------------------------------------------------------------
# Stage 16: streaming-iterator parity
# ---------------------------------------------------------------------------


def test_run_preflight_accepts_generator(record):
    """Passing a generator (not a list) must produce the same issues."""
    def gen():
        yield record

    issues = preflight.run_preflight(records=gen(), malformed=0)
    codes = {i.code for i in issues}
    # Same fixture as test_run_preflight_with_records_returns_record_count_info
    # but driven through a single-shot generator.
    assert "record-count" in codes


def test_run_preflight_generator_matches_list_output(make_record):
    """Generator and list inputs yield identical issue sequences."""
    records = [make_record(), make_record(), make_record()]
    from_list = preflight.run_preflight(records=list(records), malformed=0)

    def gen():
        for r in records:
            yield r

    from_gen = preflight.run_preflight(records=gen(), malformed=0)
    # Same codes in the same order — a strong "behavior unchanged" guarantee.
    assert [i.code for i in from_list] == [i.code for i in from_gen]


def test_run_preflight_empty_generator_yields_no_records_error():
    issues = preflight.run_preflight(records=iter([]), malformed=0)
    codes = {i.code for i in issues}
    assert "no-records" in codes


def test_run_preflight_generator_with_expected_count_mismatch(make_record):
    """expected_count is still honored when records arrive as a generator."""
    issues = preflight.run_preflight(
        records=iter([make_record()]),
        expected_count=5,
    )
    codes = {i.code for i in issues}
    assert "record-count-mismatch" in codes
