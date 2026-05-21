"""Tests for marcedit_web.lib.help_lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import help_lookup
from marcedit_web.lib.rules import parse_rules, parse_rules_text


@pytest.fixture(scope="module")
def shipped_rules():
    """Parse the shipped marc-rules.txt once for the module."""
    path = Path(__file__).resolve().parent.parent / "data" / "marc-rules.txt"
    rule_set, _ = parse_rules(path)
    return rule_set


# ---------------------------------------------------------------------------
# Field-level help
# ---------------------------------------------------------------------------


def test_field_help_basic(shipped_rules):
    entry = help_lookup.help_for(shipped_rules, tag="010")
    assert entry is not None
    assert entry.title.startswith("010 — LIBRARY OF CONGRESS CONTROL NUMBER")
    assert "non-repeatable" in entry.body
    assert "010" in entry.source


def test_field_help_unknown_tag_returns_none(shipped_rules):
    assert help_lookup.help_for(shipped_rules, tag="999") is None


def test_field_help_empty_tag_returns_none(shipped_rules):
    assert help_lookup.help_for(shipped_rules, tag="") is None


def test_field_help_renders_valid_subfields(shipped_rules):
    """Fields with a `subfield abcdef` summary surface the codes in the body."""
    entry = help_lookup.help_for(shipped_rules, tag="010")
    assert entry is not None
    assert "abz8" in entry.body  # the valid_subfield_codes for 010


def test_field_help_with_hash_continuation():
    """`####` continuation on the heading line is exposed as field-level help."""
    text = (
        "020\tR\tINTERNATIONAL STANDARD BOOK NUMBER\t####ISBN per ISO 2108.\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "subfield\tacqz68\tValid Subfields\n"
        "a\tNR\tInternational Standard Book Number\n"
    )
    rules, _ = parse_rules_text(text)
    entry = help_lookup.help_for(rules, tag="020")
    assert entry is not None
    assert "ISBN per ISO 2108." in entry.body


# ---------------------------------------------------------------------------
# Subfield-level help
# ---------------------------------------------------------------------------


def test_subfield_help_basic(shipped_rules):
    entry = help_lookup.help_for(shipped_rules, tag="010", subfield="a")
    assert entry is not None
    assert entry.title == "010 $a — LC control number"
    assert "non-repeatable" in entry.body


def test_subfield_help_empty_string_falls_back_to_field(shipped_rules):
    """An empty-string subfield argument means 'no subfield' — field help."""
    entry = help_lookup.help_for(shipped_rules, tag="010", subfield="")
    assert entry is not None
    assert "$" not in entry.title  # field-level title doesn't include subfield


def test_subfield_help_unknown_code_returns_none(shipped_rules):
    assert help_lookup.help_for(shipped_rules, tag="010", subfield="q") is None


def test_subfield_help_includes_help_text():
    text = (
        "020\tR\tISBN\n"
        "subfield\ta\tValid Subfields\n"
        "a\tNR\tInternational Standard Book Number\n"
        ":help\tThe actual ISBN, with or without hyphens.\n"
    )
    rules, _ = parse_rules_text(text)
    entry = help_lookup.help_for(rules, tag="020", subfield="a")
    assert entry is not None
    assert "with or without hyphens" in entry.body


# ---------------------------------------------------------------------------
# Byte-position help (the user's stated need)
# ---------------------------------------------------------------------------


def test_008_byte_28_is_government_publication(shipped_rules):
    entry = help_lookup.help_for(shipped_rules, tag="008", byte=28)
    assert entry is not None
    assert "Government publication" in entry.title
    assert "international intergovernmental" in entry.body


def test_008_byte_in_range_matches(shipped_rules):
    """008 bytes 0-5 declare 'Date entered on file' as a single range."""
    for byte in (0, 3, 5):
        entry = help_lookup.help_for(shipped_rules, tag="008", byte=byte)
        assert entry is not None, f"byte {byte} should have help"
        assert "Date entered on file" in entry.title


def test_008_byte_out_of_known_range_returns_none(shipped_rules):
    # We don't ship help for byte 24 (Nature of contents); should fall through.
    assert help_lookup.help_for(shipped_rules, tag="008", byte=24) is None


def test_ldr_byte_6_is_type_of_record(shipped_rules):
    entry = help_lookup.help_for(shipped_rules, tag="LDR", byte=6)
    assert entry is not None
    assert "Type of record" in entry.title


def test_ldr_byte_help_mentions_a_for_language_material(shipped_rules):
    """The user's example case: explain what a leader byte code means."""
    entry = help_lookup.help_for(shipped_rules, tag="LDR", byte=6)
    assert entry is not None
    assert "'a' = language material" in entry.body


def test_byte_lookup_on_field_with_no_byte_positions(shipped_rules):
    """010 has subfields but no byte-position entries; byte lookup → None."""
    assert help_lookup.help_for(shipped_rules, tag="010", byte=0) is None


# ---------------------------------------------------------------------------
# HelpEntry shape
# ---------------------------------------------------------------------------


def test_help_entry_is_frozen(shipped_rules):
    entry = help_lookup.help_for(shipped_rules, tag="245")
    assert entry is not None
    with pytest.raises(Exception):  # noqa: PT011 - frozen dataclass raises FrozenInstanceError
        entry.title = "rewrite attempt"  # type: ignore[misc]


def test_help_entry_source_is_traceable(shipped_rules):
    """Source string identifies which rules-file directive produced the entry."""
    entry = help_lookup.help_for(shipped_rules, tag="008", byte=28)
    assert entry is not None
    assert "marc-rules.txt" in entry.source
    assert "008" in entry.source
    assert ":byte" in entry.source
