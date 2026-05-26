"""Tests for marcedit_web.lib.search."""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import search
from marcedit_web.lib.record_store import RecordStore
from marcedit_web.lib.search import SearchQuery, matching_records, parse_query


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.mrc"


@pytest.fixture
def store(tmp_path) -> RecordStore:
    return RecordStore.from_bytes(
        FIXTURE.read_bytes(),
        tmp_dir=tmp_path / "rs",
        filename="sample.mrc",
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_empty_yields_empty_query():
    q = parse_query("")
    assert q == SearchQuery()
    assert q.is_empty()


def test_parse_plain_text():
    q = parse_query("Pistoletto")
    assert q.text == "Pistoletto"
    assert q.tag is None
    assert q.subfield is None
    assert q.byte_position is None


def test_parse_tag_only():
    q = parse_query("245:foo")
    assert q.tag == "245"
    assert q.text == "foo"
    assert q.subfield is None
    assert q.byte_position is None


def test_parse_tag_with_subfield():
    q = parse_query("245$a:Pistoletto")
    assert q.tag == "245"
    assert q.subfield == "a"
    assert q.text == "Pistoletto"
    assert q.byte_position is None


def test_parse_tag_with_byte_position():
    q = parse_query("008/28:i")
    assert q.tag == "008"
    assert q.byte_position == 28
    assert q.text == "i"
    assert q.subfield is None


def test_parse_quoted_phrase():
    q = parse_query('245$a:"exact phrase"')
    assert q.tag == "245"
    assert q.subfield == "a"
    assert q.text == "exact phrase"


def test_parse_ldr_byte():
    q = parse_query("LDR/6:a")
    assert q.tag == "LDR"
    assert q.byte_position == 6
    assert q.text == "a"


def test_parse_malformed_falls_back_to_text():
    # `weird` is not a valid tag and there's no colon
    q = parse_query("just plain text")
    assert q.tag is None
    assert q.text == "just plain text"


def test_parse_bad_byte_position_falls_back():
    # 008/abc is not a number; treat whole thing as text
    q = parse_query("008/abc:i")
    assert q.tag is None
    assert "008/abc:i" in q.text


def test_parse_bad_subfield_falls_back():
    # `$ab` is two chars; not a valid subfield code
    q = parse_query("245$ab:foo")
    assert q.tag is None
    assert q.text == "245$ab:foo"


def test_parse_treats_subfield_as_lowercase():
    q = parse_query("245$A:foo")
    assert q.subfield == "a"


def test_parse_tag_only_empty_text():
    q = parse_query("245:")
    assert q.tag == "245"
    assert q.text == ""


def test_parse_colon_in_text_after_prefix():
    q = parse_query('245$a:"foo: bar"')
    assert q.tag == "245"
    assert q.text == "foo: bar"


# ---------------------------------------------------------------------------
# Match engine
# ---------------------------------------------------------------------------


def test_empty_query_matches_everything(store):
    indices = list(matching_records(store, SearchQuery()))
    assert indices == list(range(store.count()))


def test_plain_text_finds_pistoletto(store):
    q = parse_query("Pistoletto")
    indices = list(matching_records(store, q))
    assert 0 in indices  # Record 1 is "Michelangelo Pistoletto"


def test_subfield_search_narrows_correctly(store):
    """245 $a:Pistoletto finds record 1; matches only via 245 $a.

    The phrase "Pistoletto" also lives in 600 / 700 in record 1, but
    the subfield-scoped query restricts to 245 $a.
    """
    q = parse_query("245$a:Pistoletto")
    indices = list(matching_records(store, q))
    assert indices == [0]


def test_subfield_search_no_match(store):
    q = parse_query("245$a:absurdo-not-in-fixture")
    indices = list(matching_records(store, q))
    assert indices == []


def test_byte_position_blank_matches_all_records(store):
    """008 byte 28 is space (no gov publication) on every fixture record."""
    q = parse_query("008/28: ")
    indices = list(matching_records(store, q))
    assert len(indices) == store.count()


def test_byte_position_i_matches_none(store):
    """No fixture record is an international intergovernmental publication."""
    q = parse_query("008/28:i")
    indices = list(matching_records(store, q))
    assert indices == []


def test_tag_only_searches_field_widely(store):
    q = parse_query("245:Pistoletto")
    indices = list(matching_records(store, q))
    assert 0 in indices


def test_case_insensitive_by_default(store):
    upper = list(matching_records(store, parse_query("PISTOLETTO")))
    lower = list(matching_records(store, parse_query("pistoletto")))
    assert upper == lower


def test_case_sensitive_flag_respected(store):
    q = SearchQuery(text="PISTOLETTO", case_sensitive=True)
    # The fixture has "Pistoletto" with capital P — uppercase-only query
    # should miss every record.
    indices = list(matching_records(store, q))
    assert indices == []


def test_matching_records_is_a_streaming_iterator(store):
    q = parse_query("Pistoletto")
    it = matching_records(store, q)
    first = next(it)
    assert first == 0  # we can take just the first match


# ---------------------------------------------------------------------------
# TASK-042: operator sigils + compound queries
# ---------------------------------------------------------------------------


def test_parse_starts_with_sigil():
    q = parse_query("245$a:^The")
    assert q.tag == "245"
    assert q.subfield == "a"
    assert q.text == "The"
    assert q.mode == "starts"
    assert q.parse_error is None


def test_parse_ends_with_sigil():
    q = parse_query("856$u:.pdf$")
    assert q.tag == "856"
    assert q.subfield == "u"
    assert q.text == ".pdf"
    assert q.mode == "ends"


def test_parse_regex_sigil_valid_pattern():
    q = parse_query(r"035$a:~^\(EDZ\)")
    assert q.mode == "regex"
    assert q.text == r"^\(EDZ\)"
    assert q.parse_error is None


def test_parse_regex_sigil_invalid_falls_back_with_error():
    """Bad regex degrades to contains; parse_error is populated."""
    q = parse_query("245$a:~(unbalanced")
    assert q.mode == "contains"
    assert q.parse_error and "Invalid regex" in q.parse_error


def test_parse_quoted_value_disables_operators():
    """Quoted value matches a literal caret without triggering starts-with."""
    q = parse_query('245$a:"^literal"')
    assert q.text == "^literal"
    assert q.mode == "contains"


def test_parse_compound_query_splits_on_and():
    queries = search.parse_compound_query("245$a:Pistoletto AND 008/35:e")
    assert len(queries) == 2
    assert queries[0].tag == "245" and queries[0].subfield == "a"
    assert queries[1].tag == "008" and queries[1].byte_position == 35


def test_parse_compound_query_is_case_insensitive_for_and():
    queries = search.parse_compound_query("245:foo and 100:bar")
    assert len(queries) == 2


def test_parse_compound_query_empty_input_returns_empty_list():
    assert search.parse_compound_query("") == []
    assert search.parse_compound_query("   ") == []


# ---------------------------------------------------------------------------
# Operator behavior against the fixture
# ---------------------------------------------------------------------------


def test_starts_with_does_not_match_substring(store):
    """``^Mich`` matches rec 0 (Michelangelo); ``^chelan`` (mid) does not."""
    starts = list(matching_records(store, parse_query("245$a:^Mich")))
    mid = list(matching_records(store, parse_query("245$a:^chelan")))
    assert 0 in starts
    assert mid == []


def test_ends_with_matches_value_suffix(store):
    """``245$a:absence :$`` matches rec 1 (ends with 'absence :')."""
    indices = list(matching_records(store, parse_query("245$a:absence :$")))
    assert 1 in indices
    # Mid-string substring "absence :" still wouldn't ends-with-match
    # any other record.
    assert all(i == 1 for i in indices)


def test_regex_search_matches_pattern(store):
    """Regex sigil drives an ``re.search`` against the subfield value."""
    indices = list(matching_records(store, parse_query(r"245$a:~^Mich")))
    assert 0 in indices  # "Michelangelo Pistoletto :"


def test_compound_and_returns_intersection(store):
    """Records in BOTH clauses survive AND-compound matching."""
    pistoletto = set(matching_records(store, parse_query("245$a:Pistoletto")))
    eng_byte = set(matching_records(store, parse_query("008/35:e")))
    intersection = pistoletto & eng_byte

    compound = search.parse_compound_query(
        "245$a:Pistoletto AND 008/35:e"
    )
    via_compound = set(search.matching_records_compound(store, compound))
    assert via_compound == intersection


def test_compound_with_empty_query_list_matches_everything(store):
    """An empty clause list (the "no search" case) returns every record."""
    all_indices = list(search.matching_records_compound(store, []))
    assert all_indices == list(range(store.count()))


def test_compound_short_circuits_on_failing_clause(store):
    """A clause that matches no records yields an empty intersection."""
    queries = search.parse_compound_query(
        "245$a:Pistoletto AND 245$a:^Z-NEVER-MATCHES"
    )
    assert list(search.matching_records_compound(store, queries)) == []
