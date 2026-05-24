"""Tests for marcedit_web.lib.rules_validate."""

from __future__ import annotations

import pymarc
import pytest

from marcedit_web.lib import rules_validate
from marcedit_web.lib.rules import parse_rules_text


@pytest.fixture
def basic_rules():
    """A small RuleSet covering 008, 010, 100, 110, 245.

    Designed so each validator branch has an exercising case.
    """
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
        "010\tNR\tLIBRARY OF CONGRESS CONTROL NUMBER\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "subfield\tabz8\tValid Subfields\n"
        "a\tNR\tLC control number\n"
        "b\tR\tNUCMC control number\n"
        "z\tR\tCanceled/invalid\n"
        "\n"
        "100\tR\tMAIN ENTRY--PERSONAL NAME\n"
        "ind1\t013\tType of name\n"
        "ind2\tblank\tUndefined\n"
        "subfield\tabcq\tValid Subfields\n"
        "a\tNR\tPersonal name\n"
        "\n"
        "110\tR\tMAIN ENTRY--CORPORATE NAME\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "subfield\tab\tValid Subfields\n"
        "a\tNR\tCorporate name\n"
        "\n"
        "245\tNR\tTITLE STATEMENT\n"
        "ind1\t01\tTitle added entry\n"
        "ind2\t0-9\tNonfiling characters\n"
        "subfield\tabc\tValid Subfields\n"
        "a\tNR\tTitle\n"
    )
    rule_set, warnings = parse_rules_text(text)
    assert warnings == []
    return rule_set


def _rec_with_fields(*fields):
    """Build a record with a 'good' leader and the supplied fields."""
    r = pymarc.Record()
    r.leader = pymarc.Leader("00000nam a2200000 a 4500")
    for f in fields:
        r.add_field(f)
    return r


def _ctrl(tag, data):
    return pymarc.Field(tag=tag, data=data)


def _var(tag, ind1, ind2, *pairs):
    return pymarc.Field(
        tag=tag,
        indicators=[ind1, ind2],
        subfields=[pymarc.Subfield(c, v) for c, v in pairs],
    )


# ---------------------------------------------------------------------------
# Per-record checks
# ---------------------------------------------------------------------------


def test_missing_245_flagged(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
    )
    issues = rules_validate.validate_records([r], basic_rules)
    codes = {i.code for i in issues}
    assert "rule-missing-245" in codes


def test_only_one_1xx_flagged(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
        _var("100", "1", " ", ("a", "Author, A.")),
        _var("110", " ", " ", ("a", "Org")),
        _var("245", "1", "0", ("a", "Title")),
    )
    issues = rules_validate.validate_records([r], basic_rules)
    codes = {i.code for i in issues}
    assert "rule-only-one-1xx" in codes


def test_tag_nonrepeatable_flagged(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
        _var("245", "1", "0", ("a", "First")),
        _var("245", "1", "0", ("a", "Second")),
    )
    issues = rules_validate.validate_records([r], basic_rules)
    codes = {i.code for i in issues}
    assert "rule-tag-nonrepeatable" in codes


def test_bad_indicator_flagged(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
        _var("245", "5", "0", ("a", "Title")),  # ind1=5 not in "01"
    )
    issues = rules_validate.validate_records([r], basic_rules)
    bad = [i for i in issues if i.code == "rule-bad-indicator"]
    assert bad and "ind1" in bad[0].message


def test_bad_subfield_flagged(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
        _var("245", "1", "0", ("a", "Title"), ("q", "stray")),  # q not in abc
    )
    issues = rules_validate.validate_records([r], basic_rules)
    codes = {i.code for i in issues}
    assert "rule-bad-subfield" in codes


def test_subfield_nonrepeatable_flagged(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
        _var(
            "010", " ", " ",
            ("a", "first"), ("a", "second"),  # 010$a is NR
        ),
        _var("245", "1", "0", ("a", "Title")),
    )
    issues = rules_validate.validate_records([r], basic_rules)
    codes = {i.code for i in issues}
    assert "rule-subfield-nonrepeatable" in codes


def test_length_mismatch_on_008(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "TOO SHORT"),  # not 40 bytes
        _var("245", "1", "0", ("a", "Title")),
    )
    issues = rules_validate.validate_records([r], basic_rules)
    bad = [i for i in issues if i.code == "rule-length-mismatch"]
    assert bad


def test_unknown_tag_emits_info(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
        _var("245", "1", "0", ("a", "Title")),
        _var("999", " ", " ", ("a", "Local field")),
    )
    issues = rules_validate.validate_records([r], basic_rules)
    unknown = [i for i in issues if i.code == "rule-unknown-tag"]
    assert unknown and unknown[0].severity == "info"


def test_no_issues_on_clean_record(basic_rules):
    r = _rec_with_fields(
        _ctrl("001", "X"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),  # 40 bytes
        _var("100", "1", " ", ("a", "Author, A.")),
        _var("245", "1", "0", ("a", "Title")),
        _var("010", " ", " ", ("a", "lccn-001")),
    )
    issues = rules_validate.validate_records([r], basic_rules)
    # No warnings/errors; only the (possibly empty) info-level ones
    # would survive, and our basic_rules covers every used tag.
    severity_set = {i.severity for i in issues}
    assert "warning" not in severity_set
    assert "error" not in severity_set


# ---------------------------------------------------------------------------
# Identifier and aggregate behavior
# ---------------------------------------------------------------------------


def test_issue_carries_record_index_and_identifier(basic_rules):
    r1 = _rec_with_fields(
        _ctrl("001", "AAA"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
    )
    r2 = _rec_with_fields(
        _ctrl("001", "BBB"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
    )
    issues = rules_validate.validate_records([r1, r2], basic_rules)
    missing = [i for i in issues if i.code == "rule-missing-245"]
    assert {(i.record_index, i.identifier) for i in missing} == {
        (1, "AAA"),
        (2, "BBB"),
    }


# ---------------------------------------------------------------------------
# Stage 16: streaming-iterator parity
# ---------------------------------------------------------------------------


def test_validate_records_accepts_generator(basic_rules):
    """Driving via a generator yields identical issues to driving via a list."""
    r1 = _rec_with_fields(
        _ctrl("001", "AAA"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
    )
    r2 = _rec_with_fields(
        _ctrl("001", "BBB"),
        _ctrl("008", "180706s2013    nyu     ob    001 0 eng d"),
    )
    list_issues = rules_validate.validate_records([r1, r2], basic_rules)

    def gen():
        yield r1
        yield r2

    gen_issues = rules_validate.validate_records(gen(), basic_rules)
    assert [i.code for i in list_issues] == [i.code for i in gen_issues]
    assert [i.record_index for i in list_issues] == [
        i.record_index for i in gen_issues
    ]
