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
        "value_scope": "all",
    }
    params.update(changes)
    return params


def _matrix_record_for_target(target_kind):
    record = Record()
    if target_kind == "control_field":
        record.add_field(Field(tag="001", data="TFeba-TFeba"))
    else:
        second_value = (
            "TFeba-TFeba"
            if target_kind == "all_subfields"
            else "leave-z-alone"
        )
        record.add_field(
            Field(
                tag="035",
                indicators=[" ", " "],
                subfields=[
                    Subfield(code="a", value="TFeba-TFeba"),
                    Subfield(code="z", value=second_value),
                ],
            )
        )
    return record


def _target_params(target_kind, **changes):
    if target_kind == "control_field":
        params = _params(
            target_kind=target_kind,
            tag="001",
            subfield="",
        )
    elif target_kind == "all_subfields":
        params = _params(target_kind=target_kind, subfield="")
    else:
        params = _params(target_kind=target_kind)
    params.update(changes)
    return params


def _selected_values_for_assertion(record, target_kind):
    if target_kind == "control_field":
        return [record["001"].data]
    if target_kind == "subfield":
        return [
            value
            for field in record.get_fields("035")
            for value in field.get_subfields("a")
        ]
    return [
        subfield.value
        for field in record.get_fields("035")
        for subfield in field.subfields
    ]


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


@pytest.mark.parametrize(
    ("replacement_mode", "replacement", "expected"),
    [
        ("prepend", "prefix:", ["prefix:one", "prefix:two"]),
        ("append", ":suffix", ["one:suffix", "two:suffix"]),
    ],
)
def test_prepend_append_changes_existing_values_across_fields_only(
    replacement_mode, replacement, expected
):
    record = Record()
    record.add_field(Field(
        tag="856",
        indicators=["4", "0"],
        subfields=[Subfield("u", "one")],
    ))
    record.add_field(Field(
        tag="856",
        indicators=["4", "1"],
        subfields=[Subfield("u", "two")],
    ))
    record.add_field(Field(
        tag="856",
        indicators=["4", "0"],
        subfields=[Subfield("y", "missing source")],
    ))

    guided_replace.apply_guided_find_replace(
        record,
        **_params(
            tag="856",
            subfield="u",
            match_mode="none",
            find="",
            replacement_mode=replacement_mode,
            replacement=replacement,
        ),
    )

    assert [
        value
        for field in record.get_fields("856")
        for value in field.get_subfields("u")
    ] == expected
    assert record.get_fields("856")[2].get_subfields("u") == []


def test_preexisting_generated_call_without_value_scope_still_changes_all():
    """Earlier saved task bodies retain their established all-values scope."""

    record = _record()
    params = _params(
        match_mode="none",
        find="",
        replacement_mode="append",
        replacement="(SCTFEBA)",
    )
    del params["value_scope"]

    result = guided_replace.apply_guided_find_replace(record, **params)

    assert result["changed_values"] == 2


@pytest.mark.parametrize("replacement_mode", ["prepend", "append"])
@pytest.mark.parametrize(
    ("value_scope", "changed_indexes"),
    [("all", {0, 1}), ("first", {0}), ("last", {1})],
)
def test_prepend_append_scope_selects_repeated_035_values_in_record_order(
    replacement_mode, value_scope, changed_indexes
):
    """Catalogers must be able to avoid changing every repeated 035$a."""

    record = _record()
    before = [field["a"] for field in record.get_fields("035")]
    replacement = "(SCTFEBA)"

    result = guided_replace.apply_guided_find_replace(
        record,
        **_params(
            match_mode="none",
            find="",
            replacement_mode=replacement_mode,
            replacement=replacement,
            value_scope=value_scope,
        ),
    )

    after = [field["a"] for field in record.get_fields("035")]
    for index, original in enumerate(before):
        expected = original
        if index in changed_indexes:
            expected = (
                replacement + original
                if replacement_mode == "prepend"
                else original + replacement
            )
        assert after[index] == expected
    assert result["changed_values"] == len(changed_indexes)


def test_selected_value_scope_is_validated_separately_from_text_occurrence():
    assert guided_replace.validate_request(
        **_params(value_scope="middle")
    ) == ("Selected-value scope is not supported.",)
    assert guided_replace.validate_request(
        **_params(value_scope="first")
    ) == (
        "Selected-value scope is only available for prepend or append.",
    )


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
    ("target_kind", "selected_count"),
    [
        ("control_field", 1),
        ("subfield", 1),
        ("all_subfields", 2),
    ],
    ids=[
        "control-value-keeps-actions-orthogonal",
        "one-subfield-code-keeps-actions-orthogonal",
        "all-subfield-values-keep-actions-orthogonal",
    ],
)
@pytest.mark.parametrize(
    ("replacement_mode", "changes", "expected", "matches_per_value"),
    [
        (
            "matched_text",
            {},
            "(SCTFEBA)-(SCTFEBA)",
            2,
        ),
        (
            "whole_value",
            {"replacement": "whole", "occurrences": "first"},
            "whole",
            1,
        ),
        (
            "prepend",
            {
                "match_mode": "none",
                "find": "",
                "replacement": "before:",
            },
            "before:TFeba-TFeba",
            0,
        ),
        (
            "append",
            {
                "match_mode": "none",
                "find": "",
                "replacement": ":after",
            },
            "TFeba-TFeba:after",
            0,
        ),
    ],
    ids=[
        "matched-text-preserves-unmatched-value-parts",
        "whole-selected-value-replaces-once",
        "prepend-runs-once-without-find",
        "append-runs-once-without-find",
    ],
)
def test_every_target_action_cell_validates_and_executes_independently(
    target_kind,
    selected_count,
    replacement_mode,
    changes,
    expected,
    matches_per_value,
):
    record = _matrix_record_for_target(target_kind)
    params = _target_params(
        target_kind,
        replacement_mode=replacement_mode,
        **changes,
    )

    assert guided_replace.validate_request(**params) == ()

    result = guided_replace.apply_guided_find_replace(record, **params)

    assert _selected_values_for_assertion(record, target_kind) == [
        expected
    ] * selected_count
    if target_kind == "subfield":
        assert record["035"]["z"] == "leave-z-alone"
    assert result == {
        "matched_values": selected_count,
        "changed_values": selected_count,
        "matched_occurrences": selected_count * matches_per_value,
    }


@pytest.mark.parametrize(
    (
        "match_mode",
        "replacement_mode",
        "value",
        "find",
        "replacement",
        "occurrences",
        "expected",
        "matched_occurrences",
    ),
    [
        (
            "contains",
            "matched_text",
            "xTFeba-TFebay",
            "TFeba",
            "C",
            "all",
            "xC-Cy",
            2,
        ),
        (
            "contains",
            "whole_value",
            "xTFeba-TFebay",
            "TFeba",
            "whole",
            "first",
            "whole",
            1,
        ),
        (
            "starts_with",
            "matched_text",
            "TFeba-TFeba",
            "TFeba",
            "S",
            "first",
            "S-TFeba",
            1,
        ),
        (
            "starts_with",
            "whole_value",
            "TFeba-TFeba",
            "TFeba",
            "whole",
            "first",
            "whole",
            1,
        ),
        (
            "ends_with",
            "matched_text",
            "TFeba-TFeba",
            "TFeba",
            "E",
            "first",
            "TFeba-E",
            1,
        ),
        (
            "ends_with",
            "whole_value",
            "TFeba-TFeba",
            "TFeba",
            "whole",
            "first",
            "whole",
            1,
        ),
        (
            "whole_value",
            "matched_text",
            "TFeba",
            "TFeba",
            "exact",
            "first",
            "exact",
            1,
        ),
        (
            "whole_value",
            "whole_value",
            "TFeba",
            "TFeba",
            "whole",
            "first",
            "whole",
            1,
        ),
        (
            "raw_regex",
            "matched_text",
            "TFeba12-TFeba34",
            r"TFeba(\d+)",
            r"id-\1",
            "all",
            "id-12-id-34",
            2,
        ),
        (
            "raw_regex",
            "whole_value",
            "TFeba12-TFeba34",
            r"TFeba(\d+)",
            r"first-\1",
            "first",
            "first-12",
            1,
        ),
        (
            "none",
            "prepend",
            "TFeba",
            "",
            "before:",
            "all",
            "before:TFeba",
            0,
        ),
        (
            "none",
            "append",
            "TFeba",
            "",
            ":after",
            "all",
            "TFeba:after",
            0,
        ),
    ],
    ids=[
        "contains-matched-text-replaces-every-match",
        "contains-whole-value-replaces-once-after-match",
        "starts-with-matched-text-replaces-prefix-only",
        "starts-with-whole-value-replaces-once-after-prefix-match",
        "ends-with-matched-text-replaces-suffix-only",
        "ends-with-whole-value-replaces-once-after-suffix-match",
        "whole-match-matched-text-replaces-the-exact-value",
        "whole-match-whole-value-replaces-once-after-exact-match",
        "raw-regex-matched-text-expands-every-capture",
        "raw-regex-whole-value-expands-the-first-capture",
        "no-condition-prepend-runs-once",
        "no-condition-append-runs-once",
    ],
)
def test_every_match_action_cell_validates_and_executes_with_intent(
    match_mode,
    replacement_mode,
    value,
    find,
    replacement,
    occurrences,
    expected,
    matched_occurrences,
):
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value=value)],
        )
    )
    params = _params(
        match_mode=match_mode,
        find=find,
        replacement_mode=replacement_mode,
        replacement=replacement,
        occurrences=occurrences,
    )

    assert guided_replace.validate_request(**params) == ()

    result = guided_replace.apply_guided_find_replace(record, **params)

    assert record["035"]["a"] == expected
    assert result == {
        "matched_values": 1,
        "changed_values": 1,
        "matched_occurrences": matched_occurrences,
    }


@pytest.mark.parametrize(
    ("occurrences", "expected", "matched_occurrences"),
    [
        ("first", "id-12-TFeba34", 1),
        ("all", "id-12-id-34", 2),
    ],
    ids=[
        "first-expands-only-the-first-raw-capture",
        "all-expands-every-raw-capture",
    ],
)
def test_raw_regex_first_and_all_expand_captures_per_selected_value(
    occurrences,
    expected,
    matched_occurrences,
):
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[
                Subfield(code="a", value="TFeba12-TFeba34"),
            ],
        )
    )
    params = _params(
        match_mode="raw_regex",
        find=r"TFeba(\d+)",
        replacement=r"id-\1",
        occurrences=occurrences,
    )

    result = guided_replace.apply_guided_find_replace(record, **params)

    assert record["035"]["a"] == expected
    assert result == {
        "matched_values": 1,
        "changed_values": 1,
        "matched_occurrences": matched_occurrences,
    }


@pytest.mark.parametrize(
    ("target_kind", "selected_count"),
    [
        ("control_field", 1),
        ("subfield", 4),
        ("all_subfields", 4),
    ],
    ids=[
        "control-field-has-one-independent-selected-value",
        "repeated-fields-and-codes-each-select-a-value",
        "all-subfields-across-repeated-fields-each-select-a-value",
    ],
)
@pytest.mark.parametrize(
    ("occurrences", "expected", "matches_per_value"),
    [
        ("first", "(SCTFEBA)-TFeba", 1),
        ("all", "(SCTFEBA)-(SCTFEBA)", 2),
    ],
    ids=[
        "first-means-first-in-each-selected-value",
        "all-means-all-in-each-selected-value",
    ],
)
def test_occurrence_scope_is_per_selected_value_across_target_boundaries(
    target_kind,
    selected_count,
    occurrences,
    expected,
    matches_per_value,
):
    record = Record()
    if target_kind == "control_field":
        record.add_field(Field(tag="001", data="TFeba-TFeba"))
    else:
        for field_number in range(2):
            if target_kind == "subfield":
                subfields = [
                    Subfield(code="a", value="TFeba-TFeba"),
                    Subfield(code="a", value="TFeba-TFeba"),
                    Subfield(
                        code="z",
                        value="leave-z-{0}".format(field_number),
                    ),
                ]
            else:
                subfields = [
                    Subfield(code="a", value="TFeba-TFeba"),
                    Subfield(code="z", value="TFeba-TFeba"),
                ]
            record.add_field(
                Field(
                    tag="035",
                    indicators=[" ", " "],
                    subfields=subfields,
                )
            )
    params = _target_params(target_kind, occurrences=occurrences)

    result = guided_replace.apply_guided_find_replace(record, **params)

    assert _selected_values_for_assertion(record, target_kind) == [
        expected
    ] * selected_count
    if target_kind == "subfield":
        assert [
            field["z"] for field in record.get_fields("035")
        ] == ["leave-z-0", "leave-z-1"]
    assert result == {
        "matched_values": selected_count,
        "changed_values": selected_count,
        "matched_occurrences": selected_count * matches_per_value,
    }


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


def test_raw_regex_validation_is_structural_and_does_not_compile(
    monkeypatch,
):
    monkeypatch.setattr(
        guided_replace.re,
        "compile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("raw syntax belongs in the sandbox")
        ),
    )

    errors = guided_replace.validate_request(
        **_params(
            match_mode="raw_regex",
            find=r"(TFeba)",
            replacement=r"\2",
        )
    )

    assert errors == ()


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
