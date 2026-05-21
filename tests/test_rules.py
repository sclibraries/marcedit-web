"""Tests for marcedit_web.lib.rules (the extended marc-rules.txt parser)."""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import rules
from marcedit_web.lib.rules import (
    BytePos,
    FieldRule,
    IndicatorRule,
    LengthRule,
    parse_rules,
    parse_rules_text,
)


# ---------------------------------------------------------------------------
# Bare-bones field block
# ---------------------------------------------------------------------------


def test_minimal_field_block_parses():
    text = (
        "001\tNR\tCONTROL NUMBER\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "\tNR\tUndefined\n"
    )
    rule_set, warnings = parse_rules_text(text)
    assert warnings == []
    assert "001" in rule_set.fields
    rule = rule_set.fields["001"]
    assert rule.tag == "001"
    assert rule.repeatability == "NR"
    assert rule.heading == "CONTROL NUMBER"
    assert rule.ind1.codes == "blank"
    assert rule.ind2.codes == "blank"


def test_field_with_subfields():
    text = (
        "010\tNR\tLIBRARY OF CONGRESS CONTROL NUMBER\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "subfield\tabz8\tValid Subfields\n"
        "a\tNR\tLC control number\n"
        "b\tR\tNUCMC control number\n"
        "z\tR\tCanceled/invalid LC control number\n"
        "8\tR\tField link and sequence number\n"
    )
    rule_set, warnings = parse_rules_text(text)
    assert warnings == []
    rule = rule_set.fields["010"]
    assert rule.valid_subfield_codes == "abz8"
    assert "a" in rule.subfields
    assert rule.subfields["a"].repeatability == "NR"
    assert rule.subfields["b"].repeatability == "R"
    assert rule.subfields["8"].label == "Field link and sequence number"


def test_field_with_length_exact():
    text = (
        "008\tNR\tFIXED-LENGTH DATA ELEMENTS--GENERAL INFORMATION\n"
        "length\t40\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "\tNR\tUndefined\n"
    )
    rule_set, _ = parse_rules_text(text)
    assert rule_set.fields["008"].length.exact == 40


def test_field_with_length_variant_007():
    text = (
        "007\tR\tPHYSICAL DESCRIPTION FIXED FIELD\n"
        "length\ta:8,c:6|14,d:6\n"
    )
    rule_set, _ = parse_rules_text(text)
    length = rule_set.fields["007"].length
    assert length.exact is None
    assert length.variants["a"] == [8]
    assert length.variants["c"] == [6, 14]
    assert length.variants["d"] == [6]


# ---------------------------------------------------------------------------
# Cross-record header rules
# ---------------------------------------------------------------------------


def test_cross_record_rules_parse():
    text = (
        "1xx\t1\tOnly one 1XX tag is allowed.\t####Specifies Personal Main entry.\n"
        "245\t1\tOne 245 field must be present.\t####Specifies Title.\n"
        "dedup\t001,035$a,245$ab,856$u\n"
        "\n"
    )
    rule_set, warnings = parse_rules_text(text)
    assert warnings == []
    assert rule_set.cross_record.only_one_1xx is True
    assert rule_set.cross_record.must_have_245 is True
    assert rule_set.cross_record.dedup_keys == [
        "001", "035$a", "245$ab", "856$u",
    ]


# ---------------------------------------------------------------------------
# Extended directives: ####, :help, :byte
# ---------------------------------------------------------------------------


def test_field_help_via_hash_continuation():
    text = (
        "020\tR\tINTERNATIONAL STANDARD BOOK NUMBER\t####ISBN per ISO 2108.\n"
    )
    rule_set, _ = parse_rules_text(text)
    assert rule_set.fields["020"].help_text == "ISBN per ISO 2108."


def test_help_continuation_attaches_to_last_rule():
    text = (
        "020\tR\tINTERNATIONAL STANDARD BOOK NUMBER\n"
        ":help\tThe ISBN, with or without hyphens.\n"
        "ind1\tblank\tUndefined\n"
        ":help\tISBN never uses indicators.\n"
        "subfield\tacqz\tValid Subfields\n"
        "a\tNR\tInternational Standard Book Number\n"
        ":help\tThe actual ISBN.\n"
    )
    rule_set, _ = parse_rules_text(text)
    rule = rule_set.fields["020"]
    assert rule.help_text == "The ISBN, with or without hyphens."
    assert rule.ind1.help_text == "ISBN never uses indicators."
    assert rule.subfields["a"].help_text == "The actual ISBN."


def test_help_stacks_as_paragraphs():
    text = (
        "020\tR\tISBN\n"
        ":help\tFirst paragraph.\n"
        ":help\tSecond paragraph.\n"
    )
    rule_set, _ = parse_rules_text(text)
    assert (
        rule_set.fields["020"].help_text
        == "First paragraph.\n\nSecond paragraph."
    )


def test_byte_positions_parse():
    text = (
        "008\tNR\tFIXED-LENGTH DATA ELEMENTS--GENERAL INFORMATION\n"
        "length\t40\n"
        ":byte\t0-5\tDate entered on file (YYMMDD)\n"
        ":byte\t28\tGovernment publication code\n"
        ":help\tCodes: 'i' = international intergovernmental, 'f' = federal.\n"
    )
    rule_set, warnings = parse_rules_text(text)
    assert warnings == []
    bytes_ = rule_set.fields["008"].byte_positions
    assert len(bytes_) == 2
    assert bytes_[0] == BytePos(0, 5, "Date entered on file (YYMMDD)")
    assert bytes_[1].start == 28 and bytes_[1].end == 28
    # The :help line attaches to the byte position right above it.
    assert "international intergovernmental" in bytes_[1].help_text


def test_byte_outside_field_block_warns():
    text = ":byte\t0\tStray\n"
    _, warnings = parse_rules_text(text)
    assert len(warnings) == 1
    assert "field block" in warnings[0].message


def test_byte_with_bad_range_warns():
    text = (
        "008\tNR\tFIXED\n"
        ":byte\tabc\tlabel\n"
    )
    _, warnings = parse_rules_text(text)
    assert any("not numeric" in w.message for w in warnings)


def test_help_without_target_warns():
    text = ":help\torphan help text\n"
    _, warnings = parse_rules_text(text)
    assert len(warnings) == 1
    assert "no preceding rule" in warnings[0].message


# ---------------------------------------------------------------------------
# Indicator code expansion
# ---------------------------------------------------------------------------


def test_indicator_rule_blank_means_space():
    rule = IndicatorRule(codes="blank", label="Undefined")
    assert rule.allowed_chars() == {" "}


def test_indicator_rule_b7_means_space_or_seven():
    rule = IndicatorRule(codes="b7", label="National bibliographic agency")
    assert rule.allowed_chars() == {" ", "7"}


def test_indicator_rule_range():
    rule = IndicatorRule(codes="0-9", label="Numeric")
    assert rule.allowed_chars() == set("0123456789")


def test_indicator_rule_explicit_set():
    rule = IndicatorRule(codes="01", label="Level")
    assert rule.allowed_chars() == {"0", "1"}


# ---------------------------------------------------------------------------
# Backward compat + comments
# ---------------------------------------------------------------------------


def test_comment_lines_skipped():
    text = (
        "020\tR\tISBN\n"
        "# This is a comment line.\n"
        "ind1\tblank\tUndefined\n"
    )
    rule_set, warnings = parse_rules_text(text)
    assert warnings == []
    assert rule_set.fields["020"].ind1.codes == "blank"


def test_unknown_directive_warns_but_does_not_abort():
    text = (
        "020\tR\tISBN\n"
        "weirdo\tfoo\tbar\n"
        "ind1\tblank\tUndefined\n"
    )
    rule_set, warnings = parse_rules_text(text)
    assert "020" in rule_set.fields
    assert rule_set.fields["020"].ind1 is not None
    assert any("weirdo" in w.message for w in warnings)


def test_full_marc_rules_file_loads_without_aborting():
    """Smoke: the shipped data/marc-rules.txt parses end-to-end.

    We don't pin warning counts — the file may have any number of
    pre-existing oddities. The contract is "no exception, some field
    rules captured."
    """
    rules_file = Path(__file__).parent.parent / "data" / "marc-rules.txt"
    rule_set, warnings = parse_rules(rules_file)
    # The lift ships a substantial file — at minimum, we should see
    # the well-known tags.
    for tag in ("001", "008", "010", "020", "245", "856"):
        assert tag in rule_set.fields, f"expected {tag} in rules"


def test_empty_file_yields_empty_ruleset():
    rule_set, warnings = parse_rules_text("")
    assert rule_set.fields == {}
    assert warnings == []
