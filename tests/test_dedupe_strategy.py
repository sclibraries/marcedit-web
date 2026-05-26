"""Tests for marcedit_web.lib.dedupe_strategy (TASK-043)."""

from __future__ import annotations

import io

import pymarc
import pytest

from marcedit_web.lib import dedupe_strategy as ds
from marcedit_web.lib.dedupe_strategy import (
    KeeperStrategy, StrategyParams, apply_strategy_to_groups, pick_keeper,
)


def _record_with_035s(*values: tuple[str, str]) -> pymarc.Record:
    """Build a record with one 245$a and zero-or-more 035 fields.

    ``values`` is a sequence of ``(indicator2, $a_value)`` pairs;
    one 035 field per pair. The 245 is identical across records so
    they're "matched as duplicates."
    """
    r = pymarc.Record()
    r.leader = pymarc.Leader("00000nam a2200000 a 4500")
    r.add_field(pymarc.Field(tag="001", data="dup-001"))
    r.add_field(pymarc.Field(
        tag="245",
        indicators=["1", "0"],
        subfields=[pymarc.Subfield("a", "Duplicate title.")],
    ))
    for ind2, value in values:
        r.add_field(pymarc.Field(
            tag="035",
            indicators=[" ", ind2],
            subfields=[pymarc.Subfield("a", value)],
        ))
    return r


def _build_buffer(records: list[pymarc.Record]) -> tuple[bytes, list[int]]:
    """Serialize records back-to-back; return (bytes, list_of_offsets)."""
    buf = io.BytesIO()
    offsets: list[int] = []
    for r in records:
        offsets.append(buf.tell())
        buf.write(r.as_marc())
    return buf.getvalue(), offsets


# ---------------------------------------------------------------------------
# Defensive contract
# ---------------------------------------------------------------------------


def test_pick_keeper_empty_group_raises():
    with pytest.raises(ValueError):
        pick_keeper([], b"", KeeperStrategy.FIRST_OCCURRENCE)


# ---------------------------------------------------------------------------
# FIRST_OCCURRENCE
# ---------------------------------------------------------------------------


def test_first_occurrence_returns_lead_offset():
    records = [
        _record_with_035s(("9", "EDZ001")),
        _record_with_035s(("9", "EDZ001"), ("9", "SCSK2013")),
    ]
    data, offsets = _build_buffer(records)
    chosen, matched = pick_keeper(
        offsets, data, KeeperStrategy.FIRST_OCCURRENCE,
    )
    assert chosen == offsets[0]
    assert matched is True


# ---------------------------------------------------------------------------
# MOST_FIELDS
# ---------------------------------------------------------------------------


def test_most_fields_picks_richer_record():
    """Second record has one extra 035 → MOST_FIELDS picks the second."""
    records = [
        _record_with_035s(("9", "EDZ001")),
        _record_with_035s(("9", "EDZ001"), ("9", "SCSK2013")),
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(offsets, data, KeeperStrategy.MOST_FIELDS)
    assert chosen == offsets[1]


def test_most_fields_tie_breaks_to_first():
    """Same field count → first occurrence wins the tie."""
    records = [
        _record_with_035s(("9", "EDZ001")),
        _record_with_035s(("9", "EDZ001")),  # identical structure
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(offsets, data, KeeperStrategy.MOST_FIELDS)
    assert chosen == offsets[0]


# ---------------------------------------------------------------------------
# MOST_OF_TAG — direct user example: keep record with more 035s
# ---------------------------------------------------------------------------


def test_most_of_tag_picks_record_with_extra_035():
    """The user's reported scenario: record with EDZ + SCSK 035s wins."""
    records = [
        _record_with_035s(("9", "EDZ0000159040")),
        _record_with_035s(("9", "EDZ0000159040"), ("9", "SCSK2013")),
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.MOST_OF_TAG,
        StrategyParams(tag="035"),
    )
    assert chosen == offsets[1]


def test_most_of_tag_no_target_tag_falls_back_to_first():
    """If params.tag is unset, fall back to first occurrence."""
    records = [_record_with_035s(("9", "X")), _record_with_035s(("9", "Y"))]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.MOST_OF_TAG,
        StrategyParams(tag=None),
    )
    assert chosen == offsets[0]


def test_most_of_tag_tie_breaks_to_first():
    records = [
        _record_with_035s(("9", "EDZ")),
        _record_with_035s(("9", "OCN")),
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.MOST_OF_TAG,
        StrategyParams(tag="035"),
    )
    # Both have one 035 → first wins.
    assert chosen == offsets[0]


# ---------------------------------------------------------------------------
# FIELD_MATCHES_REGEX — direct user example: ^SCSK pattern
# ---------------------------------------------------------------------------


def test_field_matches_regex_finds_scsk_record():
    """User's scenario: pattern ``^SCSK`` picks the SCSK record."""
    records = [
        _record_with_035s(("9", "EDZ0000159040")),  # no SCSK
        _record_with_035s(("9", "SCSK2013")),
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern=r"^SCSK"),
    )
    assert chosen == offsets[1]


def test_field_matches_regex_picks_first_match_among_many():
    """Multiple matches → first in group order wins."""
    records = [
        _record_with_035s(("9", "EDZ001")),
        _record_with_035s(("9", "SCSK001")),
        _record_with_035s(("9", "SCSK002")),
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern=r"^SCSK"),
    )
    assert chosen == offsets[1]  # not offsets[2]


def test_field_matches_regex_no_match_falls_back_to_first():
    """No member matches the pattern → first occurrence is the keeper."""
    records = [
        _record_with_035s(("9", "EDZ001")),
        _record_with_035s(("9", "OCN001")),
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern=r"^SCSK"),
    )
    assert chosen == offsets[0]


def test_field_matches_regex_case_insensitive_by_default():
    """``params.case_sensitive=False`` (default) → lowercase pattern matches."""
    records = [
        _record_with_035s(("9", "EDZ001")),
        _record_with_035s(("9", "scsk2013")),  # lowercase
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern=r"^SCSK"),
    )
    assert chosen == offsets[1]


def test_field_matches_regex_case_sensitive_flag_respected():
    records = [
        _record_with_035s(("9", "EDZ001")),
        _record_with_035s(("9", "scsk2013")),
    ]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(
            tag="035", subfield="a", pattern=r"^SCSK", case_sensitive=True,
        ),
    )
    # Case-sensitive: lowercase doesn't match → first-occurrence fallback.
    assert chosen == offsets[0]


def test_field_matches_regex_bad_pattern_falls_back():
    """An invalid regex degrades to first-occurrence instead of raising."""
    records = [_record_with_035s(("9", "X")), _record_with_035s(("9", "Y"))]
    data, offsets = _build_buffer(records)
    chosen, _matched = pick_keeper(
        offsets, data,
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern="(unbalanced"),
    )
    assert chosen == offsets[0]


# ---------------------------------------------------------------------------
# apply_strategy_to_groups
# ---------------------------------------------------------------------------


def test_apply_strategy_returns_one_keeper_per_group():
    rec_a = _record_with_035s(("9", "EDZ001"))
    rec_b = _record_with_035s(("9", "EDZ001"), ("9", "SCSK001"))
    rec_c = _record_with_035s(("9", "OCN001"))
    rec_d = _record_with_035s(("9", "OCN001"), ("9", "SCSK002"))
    data, offsets = _build_buffer([rec_a, rec_b, rec_c, rec_d])
    dup_groups = {
        "group-edz": [offsets[0], offsets[1]],
        "group-ocn": [offsets[2], offsets[3]],
    }
    keepers, matched = apply_strategy_to_groups(
        dup_groups, data,
        KeeperStrategy.MOST_OF_TAG,
        StrategyParams(tag="035"),
    )
    assert keepers["group-edz"] == offsets[1]   # rec_b: 2× 035
    assert keepers["group-ocn"] == offsets[3]   # rec_d: 2× 035
    assert matched == 2


def test_apply_strategy_empty_groups_returns_empty():
    keepers, matched = apply_strategy_to_groups(
        {}, b"", KeeperStrategy.FIRST_OCCURRENCE,
    )
    assert keepers == {}
    assert matched == 0


# ---------------------------------------------------------------------------
# TASK-044: validate_params + matched_count for regex strategy
# ---------------------------------------------------------------------------


def test_validate_params_first_occurrence_always_ok():
    assert ds.validate_params(
        KeeperStrategy.FIRST_OCCURRENCE, StrategyParams(),
    ) is None


def test_validate_params_most_fields_always_ok():
    assert ds.validate_params(
        KeeperStrategy.MOST_FIELDS, StrategyParams(),
    ) is None


def test_validate_params_most_of_tag_requires_tag():
    err = ds.validate_params(
        KeeperStrategy.MOST_OF_TAG, StrategyParams(tag=None),
    )
    assert err and "tag" in err.lower()


def test_validate_params_regex_requires_tag_and_pattern():
    no_tag = ds.validate_params(
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag=None, pattern="^x"),
    )
    no_pattern = ds.validate_params(
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", pattern=None),
    )
    assert no_tag and "tag" in no_tag.lower()
    assert no_pattern and "pattern" in no_pattern.lower()


def test_validate_params_regex_rejects_unbalanced_paren():
    """The user's actual bug: ``^(SCSK`` blows up regex compile."""
    err = ds.validate_params(
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern="^(SCSK"),
    )
    assert err is not None
    assert "Invalid regex" in err
    # The error message points at how to escape literal parens.
    assert "\\(" in err and "\\)" in err


def test_validate_params_regex_accepts_escaped_paren():
    """``^\\(SCSK`` (escaped paren) is the corrected pattern."""
    err = ds.validate_params(
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern=r"^\(SCSK"),
    )
    assert err is None


def test_apply_strategy_regex_matched_count_only_counts_hits():
    """matched_count == groups where the regex actually matched."""
    rec_edz = _record_with_035s(("9", "EDZ001"))
    rec_scsk = _record_with_035s(("9", "(SCSK2013)42"))
    rec_ocn = _record_with_035s(("9", "OCN001"))
    data, offsets = _build_buffer([rec_edz, rec_scsk, rec_ocn])
    dup_groups = {
        "g1": [offsets[0], offsets[1]],  # SCSK match available
        "g2": [offsets[0], offsets[2]],  # no SCSK
    }
    keepers, matched = apply_strategy_to_groups(
        dup_groups, data,
        KeeperStrategy.FIELD_MATCHES_REGEX,
        StrategyParams(tag="035", subfield="a", pattern=r"^\(SCSK"),
    )
    assert keepers["g1"] == offsets[1]  # SCSK picked
    assert keepers["g2"] == offsets[0]  # fallback to first
    assert matched == 1  # only g1 actually hit the pattern
