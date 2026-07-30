from __future__ import annotations

import pytest
from pymarc import Field, Record, Subfield

from marcedit_web.lib import guided_replace


def _record():
    record = Record()
    record.add_field(Field(tag="001", data="TFeba123"))
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[
                Subfield(code="a", value="TFeba9780020306634"),
                Subfield(code="z", value="keep"),
            ],
        )
    )
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value="prefix-TFeba-suffix")],
        )
    )
    return record


def _params(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "contains",
        "find": "TFeba",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "(SCTFEBA)",
        "occurrences": "all",
    }
    params.update(changes)
    return params


def _valid_params_for(target_kind, replacement_mode):
    params = _params(
        target_kind=target_kind,
        replacement_mode=replacement_mode,
    )
    if target_kind == "control_field":
        params.update(tag="001", subfield="")
    elif target_kind == "all_subfields":
        params.update(tag="035", subfield="")
    if replacement_mode in ("prepend", "append"):
        params.update(match_mode="none", find="", occurrences="all")
    elif replacement_mode == "whole_value":
        params.update(occurrences="first")
    return params


def test_matched_text_default_preserves_identifier_after_035_match():
    record = _record()

    result = guided_replace.apply_guided_find_replace(record, **_params())

    assert record["035"]["a"] == "(SCTFEBA)9780020306634"
    assert result == {
        "matched_values": 2,
        "changed_values": 2,
        "matched_occurrences": 2,
    }


def test_prepend_has_no_find_or_regex_and_runs_once_per_selected_value():
    record = _record()
    params = _params(
        match_mode="none",
        find="",
        replacement_mode="prepend",
        replacement="(OCoLC)",
    )

    result = guided_replace.apply_guided_find_replace(record, **params)

    assert record.get_fields("035")[0]["a"] == (
        "(OCoLC)TFeba9780020306634"
    )
    assert result["matched_values"] == 2
    assert result["matched_occurrences"] == 0


def test_empty_find_is_rejected_for_matched_text():
    errors = guided_replace.validate_request(**_params(find=""))
    assert errors == ("Find text is required for matched-text replacement.",)


def test_prepend_rejects_hidden_regex_state():
    errors = guided_replace.validate_request(
        **_params(
            match_mode="raw_regex",
            find="TFeba",
            replacement_mode="prepend",
        )
    )
    assert "prepend requires match mode 'none' and an empty Find value." in errors


def test_guided_replacement_backslashes_are_literal_not_capture_syntax():
    record = _record()
    guided_replace.apply_guided_find_replace(
        record, **_params(replacement=r"\1")
    )
    assert record["035"]["a"] == r"\19780020306634"


@pytest.mark.parametrize(
    ("match_mode", "value", "find", "expected"),
    [
        ("contains", "xTFebay", "TFeba", "x(SCTFEBA)y"),
        ("starts_with", "TFebay", "TFeba", "(SCTFEBA)y"),
        ("starts_with", "xTFeba", "TFeba", "xTFeba"),
        ("ends_with", "xTFeba", "TFeba", "x(SCTFEBA)"),
        ("whole_value", "TFeba", "TFeba", "(SCTFEBA)"),
        ("whole_value", "TFeba123", "TFeba", "TFeba123"),
        ("raw_regex", "TFeba123", r"^(TFeba)(\d+)$", "(SCTFEBA)123"),
    ],
    ids=[
        "contains-preserves-both-sides",
        "starts-with-replaces-prefix",
        "starts-with-does-not-match-middle",
        "ends-with-replaces-suffix",
        "whole-value-replaces-equal-value",
        "whole-value-preserves-non-equal-value",
        "raw-regex-expands-capture",
    ],
)
def test_match_modes_replace_only_the_matched_text(
    match_mode, value, find, expected
):
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value=value)],
        )
    )
    params = _params(match_mode=match_mode, find=find)
    if match_mode in ("starts_with", "ends_with", "whole_value"):
        params["occurrences"] = "first"
    if match_mode == "raw_regex":
        params["replacement"] = r"(SCTFEBA)\2"
    guided_replace.apply_guided_find_replace(record, **params)
    assert record["035"]["a"] == expected


@pytest.mark.parametrize(
    "target_kind",
    ["control_field", "subfield", "all_subfields"],
)
@pytest.mark.parametrize(
    "replacement_mode",
    ["matched_text", "whole_value", "prepend", "append"],
)
def test_every_target_action_cell_is_supported(
    target_kind, replacement_mode
):
    params = _valid_params_for(target_kind, replacement_mode)
    assert guided_replace.validate_request(**params) == ()


def test_first_and_all_are_per_selected_value_not_per_record():
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[
                Subfield(code="a", value="TFeba-TFeba"),
                Subfield(code="a", value="TFeba-TFeba"),
            ],
        )
    )
    params = _params(occurrences="first")
    guided_replace.apply_guided_find_replace(record, **params)
    assert record["035"].get_subfields("a") == [
        "(SCTFEBA)-TFeba",
        "(SCTFEBA)-TFeba",
    ]


def test_ignore_case_matches_without_changing_unmatched_text_case():
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value="prefix-tfEBA-suffix")],
        )
    )

    result = guided_replace.apply_guided_find_replace(
        record, **_params(ignore_case=True)
    )

    assert record["035"]["a"] == "prefix-(SCTFEBA)-suffix"
    assert result["matched_occurrences"] == 1


def test_repeated_fields_and_all_subfields_are_each_selected():
    record = _record()

    result = guided_replace.apply_guided_find_replace(
        record,
        **_params(
            target_kind="all_subfields",
            subfield="",
            match_mode="none",
            find="",
            replacement_mode="append",
            replacement="!",
        ),
    )

    assert [
        item.value for item in record.get_fields("035")[0].subfields
    ] == [
        "TFeba9780020306634!",
        "keep!",
    ]
    assert [
        item.value for item in record.get_fields("035")[1].subfields
    ] == [
        "prefix-TFeba-suffix!"
    ]
    assert result == {
        "matched_values": 3,
        "changed_values": 3,
        "matched_occurrences": 0,
    }


def test_no_match_leaves_selected_value_and_counts_unchanged():
    record = _record()

    result = guided_replace.apply_guided_find_replace(
        record, **_params(find="absent")
    )

    assert record["035"]["a"] == "TFeba9780020306634"
    assert result == {
        "matched_values": 0,
        "changed_values": 0,
        "matched_occurrences": 0,
    }


def test_unchanged_replacement_counts_match_but_not_change():
    record = _record()

    result = guided_replace.apply_guided_find_replace(
        record, **_params(replacement="TFeba")
    )

    assert result == {
        "matched_values": 2,
        "changed_values": 0,
        "matched_occurrences": 2,
    }


@pytest.mark.parametrize("tag", ["001", "009"])
def test_control_field_boundaries_are_replaceable(tag):
    record = Record()
    record.add_field(Field(tag=tag, data="TFeba123"))

    result = guided_replace.apply_guided_find_replace(
        record,
        **_params(
            target_kind="control_field",
            tag=tag,
            subfield="",
        ),
    )

    assert record[tag].data == "(SCTFEBA)123"
    assert result["changed_values"] == 1


@pytest.mark.parametrize(
    ("target_kind", "tag", "expected"),
    [
        (
            "control_field",
            "000",
            "Control-field target must be 001 through 009.",
        ),
        (
            "control_field",
            "010",
            "Control-field target must be 001 through 009.",
        ),
        (
            "subfield",
            "009",
            "Subfield target must use tag 010 through 999.",
        ),
    ],
)
def test_target_boundaries_reject_record_leader_and_wrong_field_class(
    target_kind, tag, expected
):
    params = _params(target_kind=target_kind, tag=tag)
    if target_kind == "control_field":
        params["subfield"] = ""
    assert expected in guided_replace.validate_request(**params)


@pytest.mark.parametrize("subfield", ["", "A", "$", "aa"])
def test_subfield_code_rejects_values_outside_one_lowercase_alphanumeric(
    subfield,
):
    errors = guided_replace.validate_request(**_params(subfield=subfield))
    assert "Subfield code must be one lowercase letter or digit." in errors


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("target_kind", "field", "Target type is not supported."),
        ("match_mode", "glob", "Match mode is not supported."),
        (
            "replacement_mode",
            "surround",
            "Replacement mode is not supported.",
        ),
        ("occurrences", "second", "Occurrence mode is not supported."),
    ],
)
def test_unknown_modes_fail_validation(key, value, expected):
    errors = guided_replace.validate_request(**_params(**{key: value}))
    assert expected in errors


def test_raw_regex_invalid_capture_is_rejected_before_execution():
    errors = guided_replace.validate_request(
        **_params(
            match_mode="raw_regex",
            find=r"(TFeba)",
            replacement=r"\2",
        )
    )
    assert any(
        error.startswith("Regular expression is invalid:")
        for error in errors
    )


def test_validation_failure_does_not_mutate_input_record():
    record = _record()
    before = record.as_marc()

    with pytest.raises(ValueError, match="Find text is required"):
        guided_replace.apply_guided_find_replace(
            record, **_params(find="")
        )

    assert record.as_marc() == before


def test_whole_selected_value_uses_raw_capture_from_first_match():
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value="prefix-TFeba123-suffix")],
        )
    )

    result = guided_replace.apply_guided_find_replace(
        record,
        **_params(
            match_mode="raw_regex",
            find=r"TFeba(\d+)",
            replacement_mode="whole_value",
            replacement=r"(SCTFEBA)\1",
            occurrences="first",
        ),
    )

    assert record["035"]["a"] == "(SCTFEBA)123"
    assert result == {
        "matched_values": 1,
        "changed_values": 1,
        "matched_occurrences": 1,
    }


def test_non_text_input_is_reported_without_attempting_other_validation():
    errors = guided_replace.validate_request(
        **_params(tag=35, ignore_case="false")
    )
    assert errors == (
        "Tag must be text.",
        "Ignore-case setting must be true or false.",
    )
