"""Lossless parsing tests for external MARC field syntax."""

from __future__ import annotations

import pytest

from marcedit_web.lib.external_field_syntax import (
    parse_build_template,
    parse_leader_condition,
    parse_mnemonic_field,
    render_external_field,
)


def test_control_and_data_references_parse_in_order():
    parsed = parse_build_template(
        "=856  40$uhttps://proxy/?url={857$u}$yLink to resource"
    )
    assert parsed["tag"] == "856"
    assert parsed["ind1"] == "4"
    assert parsed["ind2"] == "0"
    assert parsed["structured_subfields"][0][0] == "u"
    assert parsed["structured_subfields"][0][1][-1] == {
        "type": "data_subfield", "tag": "857", "code": "u"
    }


@pytest.mark.parametrize(
    "template",
    [
        "=035  9\\$a({003}){001}",
        "=876  \\\\$aB({003}){001}-SC$lInternet",
        "=852  0\\$h{050$a} {050$b}$lONLINE",
    ],
)
def test_corpus_templates_round_trip_without_text_loss(template):
    assert render_external_field(parse_build_template(template)) == template


def test_plain_mnemonic_field_preserves_subfield_order_and_backslashes():
    value = "=852  8\\$hOnline$tOther scheme$lSCINT"

    assert parse_mnemonic_field(value) == {
        "tag": "852",
        "ind1": "8",
        "ind2": " ",
        "subfields": [
            ["h", "Online"],
            ["t", "Other scheme"],
            ["l", "SCINT"],
        ],
    }
    assert render_external_field(parse_mnemonic_field(value)) == value


@pytest.mark.parametrize(
    "template",
    [
        "=035  9\\$aValue",
        "=852  \\0$hValue",
        "=876  \\\\$aValue",
    ],
)
def test_every_accepted_blank_indicator_spelling_round_trips(template):
    assert render_external_field(parse_build_template(template)) == template


@pytest.mark.parametrize(
    "template",
    [
        "=035  9 $aValue",
        "=852   0$hValue",
        "=876    $aValue",
    ],
)
def test_literal_space_indicator_spellings_are_rejected(template):
    with pytest.raises(ValueError, match="backslash for a blank"):
        parse_build_template(template)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("=85X  \\\\$aValue", "three numeric"),
        ("=852  \\\\$", "incomplete subfield marker"),
        ("=852  \\\\$aLiteral {brace}", "unsupported brace"),
        ("=852  \\\\$a{050$a.ToUpper()}", "unsupported brace"),
        ("=852  \\\\$a{050$a}[x]", "multi-field"),
    ],
)
def test_build_template_rejects_ambiguous_or_lossy_syntax(value, message):
    with pytest.raises(ValueError, match=message):
        parse_build_template(value)


@pytest.mark.parametrize(
    ("external", "condition"),
    [
        ("", "always"),
        ("///=LDR.{8}[amt][m].+///", "books"),
        ("/=LDR.{9}s.+/", "serials"),
        ("=LDR.{8}[e,f].+", "maps"),
    ],
)
def test_leader_condition_accepts_only_anchored_reviewed_signatures(
    external, condition
):
    assert parse_leader_condition(external) == condition


def test_unknown_leader_condition_fails_closed():
    with pytest.raises(ValueError, match="unsupported Leader condition"):
        parse_leader_condition("=LDR.*")
