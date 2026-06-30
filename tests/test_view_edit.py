"""Tests for marcedit_web.lib.view_edit (single-record .mrk save helper)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import mrk_writer, view_edit
from marcedit_web.lib.rules import parse_rules_text


@pytest.fixture
def rule_set():
    """A minimal rule set sufficient to exercise per-record validation."""
    text = (
        "1xx\t1\tOnly one 1XX allowed.\n"
        "245\t1\tOne 245 required.\n"
        "\n"
        "001\tNR\tCONTROL NUMBER\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "\n"
        "008\tNR\tFIXED-LENGTH DATA ELEMENTS--GENERAL INFORMATION\n"
        "length\t40\n"
        "\n"
        "245\tNR\tTITLE STATEMENT\n"
        "ind1\t01\tTitle added entry\n"
        "ind2\t0-9\tNonfiling characters\n"
        "subfield\tabc\tValid Subfields\n"
        "a\tNR\tTitle\n"
    )
    rs, warnings = parse_rules_text(text)
    assert warnings == []
    return rs


def _record_mrk(record) -> str:
    """The same .mrk text the View page hands to the editor."""
    return mrk_writer.render_records_mrk([record])


# ---------------------------------------------------------------------------
# Happy path — unchanged round-trip
# ---------------------------------------------------------------------------


def test_unchanged_text_parses_back_to_same_record(record, rule_set):
    """A no-op edit (same .mrk in) yields a save-able result."""
    text = _record_mrk(record)
    result = view_edit.parse_and_validate_single_record(text, rule_set)
    assert result.can_save is True
    assert result.fatal_errors == []
    assert result.record is not None
    assert result.record.get("001").data == "1234567890"


def test_valid_edit_changes_a_subfield(record, rule_set):
    """Editing 245$a value still saves cleanly."""
    text = _record_mrk(record).replace("Test title.", "Edited title.")
    result = view_edit.parse_and_validate_single_record(text, rule_set)
    assert result.can_save
    assert "Edited title." in str(result.record.get_fields("245")[0])


# ---------------------------------------------------------------------------
# Fatal: wrong record count
# ---------------------------------------------------------------------------


def test_empty_text_fails_with_no_record_error(rule_set):
    result = view_edit.parse_and_validate_single_record("", rule_set)
    assert result.can_save is False
    assert any("No record found" in e for e in result.fatal_errors)


def test_two_records_in_buffer_is_a_fatal_error(record, rule_set):
    """Pasting a second record in by accident — block save."""
    one = _record_mrk(record)
    text = one + "\n" + one
    result = view_edit.parse_and_validate_single_record(text, rule_set)
    assert result.can_save is False
    assert any("expected exactly one" in e for e in result.fatal_errors)


# ---------------------------------------------------------------------------
# Fatal: malformed .mrk
# ---------------------------------------------------------------------------


def test_missing_leader_blocks_save(record, rule_set):
    """Removing the =LDR line is a fatal parse error."""
    text = "\n".join(
        line for line in _record_mrk(record).splitlines()
        if not line.startswith("=LDR")
    )
    result = view_edit.parse_and_validate_single_record(text, rule_set)
    assert result.can_save is False
    assert result.fatal_errors


def test_bad_line_blocks_save(record, rule_set):
    """A junk line that doesn't match =NNN format trips bad-line."""
    text = _record_mrk(record) + "\nNOT A REAL FIELD LINE\n"
    result = view_edit.parse_and_validate_single_record(text, rule_set)
    assert result.can_save is False


# ---------------------------------------------------------------------------
# Warnings + info don't block save
# ---------------------------------------------------------------------------


def test_warning_severity_does_not_block_save(record, rule_set):
    """Adding an unknown tag yields an info rule-unknown-tag; still saves.

    Insert the new field BEFORE the trailing blank line so the parser
    sees it as part of the same record (mrk_writer emits a blank-line
    separator between records, so naive append creates a 2-record
    buffer).
    """
    mrk = _record_mrk(record).rstrip("\n")
    text = mrk + "\n=999  \\\\$alocal-data-here\n"
    result = view_edit.parse_and_validate_single_record(text, rule_set)
    # `999` isn't in our rule_set, so it raises an info-level
    # rule-unknown-tag — not fatal.
    assert result.can_save is True
    assert any("rule-unknown-tag" in m for m in result.info)


def test_load_readiness_warnings_are_visible_before_save(record, rule_set):
    """FOLIO/EDS CC readiness warnings should appear in record-editor save review."""
    result = view_edit.parse_and_validate_single_record(_record_mrk(record), rule_set)

    assert result.can_save is True
    assert any("load-missing-006" in msg for msg in result.warnings)
    assert any("load-missing-007" in msg for msg in result.warnings)


# ---------------------------------------------------------------------------
# Rule set is optional (no validation when omitted)
# ---------------------------------------------------------------------------


def test_validation_skipped_when_rule_set_is_none(record):
    text = _record_mrk(record)
    result = view_edit.parse_and_validate_single_record(text, rule_set=None)
    assert result.can_save
    # Preflight still ran (always emits a `record-count` info row even
    # for a clean single record) but no rule-* validation is layered on
    # top when rule_set is None.
    rule_codes = {iss.code for iss in result.rule_issues}
    assert "record-count" in rule_codes
    assert not any(code.startswith("rule-") for code in rule_codes)
