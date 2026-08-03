import pytest
from pymarc import Field, Subfield

from marcedit_web.lib.field_predicates import (
    field_matches,
    validate_field_predicate,
)


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ({"ind1": "4", "ind2_not": "0"}, True),
        ({"ind1": "4", "ind2": "0"}, False),
        ({
            "subfield_matches": [{
                "code": "3",
                "mode": "contains",
                "value": "JSTOR",
                "ignore_case": False,
            }],
        }, True),
        ({
            "subfield_matches": [{
                "code": "3", "mode": "exists", "value": "*",
                "ignore_case": False,
            }],
        }, True),
        ({
            "subfield_matches": [{
                "code": "3", "mode": "regex", "value": "^JSTOR\\s",
                "ignore_case": False,
            }],
        }, True),
    ],
)
def test_predicates_match_fields_without_serializing_mrk(predicate, expected):
    field = Field(
        tag="856",
        indicators=["4", "1"],
        subfields=[Subfield("3", "JSTOR collection")],
    )

    assert field_matches(field, predicate) is expected


@pytest.mark.parametrize(
    ("predicate", "message"),
    [
        ({}, "at least one"),
        ({"unknown": "x"}, "unknown predicate key"),
        ({"ind1": "4", "ind1_not": "4"}, "contradictory"),
        ({"subfield_matches": []}, "at least one"),
        ({"subfield_matches": [{"code": "aa", "mode": "contains", "value": "x", "ignore_case": False}]}, "code"),
        ({"subfield_matches": [{"code": "a", "mode": "near", "value": "x", "ignore_case": False}]}, "mode"),
        ({"subfield_matches": [{"code": "a", "mode": "contains", "value": "", "ignore_case": False}]}, "nonempty"),
        ({"subfield_matches": [{"code": "a", "mode": "exists", "value": "anything", "ignore_case": False}]}, "value"),
        ({"subfield_matches": [{"code": "a", "mode": "contains", "value": "x", "ignore_case": "false"}]}, "ignore_case"),
    ],
)
def test_predicate_validation_rejects_ambiguous_or_malformed_input(
    predicate, message
):
    assert any(
        message in error for error in validate_field_predicate(predicate)
    )


def test_control_fields_reject_indicator_or_subfield_predicates():
    field = Field(tag="001", data="12345")

    with pytest.raises(ValueError, match="control field"):
        field_matches(field, {"ind1": " "})


def test_case_insensitive_regex_preserves_regex_escape_meaning():
    field = Field(
        tag="856",
        indicators=["4", "1"],
        subfields=[Subfield("3", "JSTOR")],
    )

    assert field_matches(field, {
        "subfield_matches": [{
            "code": "3", "mode": "regex", "value": r"^\S+$",
            "ignore_case": True,
        }],
    }) is True
