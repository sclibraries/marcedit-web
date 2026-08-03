import pymarc
import pytest

from marcedit_web.lib import structural_replace


def _record():
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(
        tag="035", indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "TFeba9780203066140")],
    ))
    record.add_field(pymarc.Field(
        tag="245", indicators=["1", "0"],
        subfields=[pymarc.Subfield("a", "A title")],
    ))
    return record


def test_whole_data_field_replacement_preserves_only_explicit_replacement():
    record = _record()
    result = structural_replace.apply_structural_find_replace(
        record,
        target_kind="data_field",
        tag="035",
        match_mode="contains",
        find="TFeba",
        action="replace_field",
        replacement_ind1=" ",
        replacement_ind2=" ",
        replacement_subfields=[["a", "(SCTFEBA)9780203066140"]],
    )

    assert result["changed_fields"] == 1
    assert record.get("035").get_subfields("a") == ["(SCTFEBA)9780203066140"]


def test_retag_and_indicator_actions_are_conditional():
    record = _record()
    structural_replace.apply_structural_find_replace(
        record,
        target_kind="field_tag",
        tag="035",
        match_mode="contains",
        find="TFeba",
        action="retag",
        destination_tag="936",
    )
    assert record.get("035") is None
    assert record.get("936") is not None

    structural_replace.apply_structural_find_replace(
        record,
        target_kind="indicators",
        tag="936",
        match_mode="contains",
        find="TFeba",
        action="set_indicators",
        new_ind1=" ",
        new_ind2="9",
    )
    assert list(record.get("936").indicators) == [" ", "9"]


def test_tag_range_does_not_cross_control_data_boundary():
    errors = structural_replace.validate_request(
            target_kind="tag_range",
            start_tag="008",
            end_tag="010",
            match_mode="contains",
            find="x",
            action="retag",
            destination_tag="011",
        )
    assert any("cannot cross" in error for error in errors)


@pytest.mark.parametrize(
    ("target", "action"),
    [
        ("subfield", "replace_field"),
        ("all_subfields", "retag"),
        ("data_field", "replace_matched_text"),
        ("field_tag", "set_indicators"),
        ("indicators", "replace_matched_text"),
        ("tag_range", "replace_matched_text"),
    ],
)
def test_incompatible_target_action_cells_fail_validation(target, action):
    request = {
        "target_kind": target,
        "tag": "035",
        "start_tag": "010",
        "end_tag": "099",
        "subfield": "a",
        "match_mode": "contains",
        "find": "x",
        "action": action,
        "replacement_subfields": [["a", "x"]],
        "destination_tag": "936",
        "new_ind1": " ",
        "new_ind2": " ",
        "match_ind1": "*",
        "match_ind2": "*",
    }
    errors = structural_replace.validate_request(**request)
    assert any("incompatible" in error for error in errors)


def test_control_range_allows_only_same_class_retagging():
    errors = structural_replace.validate_request(
        target_kind="tag_range",
        start_tag="001",
        end_tag="009",
        match_mode="all",
        find="",
        action="retag",
        destination_tag="010",
    )
    assert any("same control/data" in error for error in errors)
    assert not structural_replace.validate_request(
        target_kind="tag_range",
        start_tag="001",
        end_tag="009",
        match_mode="all",
        find="",
        action="retag",
        destination_tag="009",
    )


def test_named_structured_pattern_captures_round_trip():
    pieces = [
        {"type": "literal", "value": "TFeba"},
        {"type": "digits", "name": "isbn"},
    ]
    replacement = [{"type": "literal", "value": "(SCTFEBA)"}, {"type": "capture", "name": "isbn"}]
    request = structural_replace.normalize_request(
        {
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "structured",
            "pattern_pieces": pieces,
            "action": "replace_matched_text",
            "replacement_pieces": replacement,
        }
    )
    record = _record()
    structural_replace.apply_structural_find_replace(record, **request)
    assert record.get("035").get_subfields("a") == ["(SCTFEBA)9780203066140"]


def test_matched_text_replacement_rejects_empty_find_before_execution():
    errors = structural_replace.validate_request(
        target_kind="subfield",
        tag="035",
        subfield="a",
        match_mode="contains",
        find="",
        action="replace_matched_text",
        replacement="X",
    )
    assert any("Find text is required" in error for error in errors)


def test_structural_pattern_requires_at_least_one_piece():
    errors = structural_replace.validate_request(
        target_kind="subfield",
        tag="035",
        subfield="a",
        match_mode="structured",
        pattern_pieces=[],
        replacement_pieces=[],
        action="replace_matched_text",
    )
    assert any("pattern piece is required" in error for error in errors)


def test_empty_find_does_not_implicitly_mean_every_field_for_retag():
    errors = structural_replace.validate_request(
        target_kind="field_tag",
        tag="035",
        match_mode="contains",
        find="",
        action="retag",
        destination_tag="936",
    )
    assert any("Find text is required" in error for error in errors)


def test_explicit_all_mode_retags_and_preserves_source_position():
    record = _record()
    before_tags = [field.tag for field in record.fields]
    result = structural_replace.apply_structural_find_replace(
        record,
        target_kind="field_tag",
        tag="035",
        match_mode="all",
        find="",
        action="retag",
        destination_tag="936",
    )
    assert result["changed_fields"] == 1
    assert [field.tag for field in record.fields] == ["936", "245"]
    assert before_tags == ["035", "245"]


def test_invalid_raw_regex_capture_reference_is_a_validation_error():
    errors = structural_replace.validate_request(
        target_kind="subfield",
        tag="035",
        subfield="a",
        match_mode="raw_regex",
        find="(TFeba)",
        action="replace_matched_text",
        replacement=r"\9",
    )
    assert any("replacement" in error and "group" in error for error in errors)


def test_predicate_aware_retag_matches_only_the_selected_indicator_matrix():
    record = pymarc.Record()
    for indicators in (["4", "0"], ["4", "1"], ["3", "1"]):
        record.add_field(pymarc.Field(
            tag="856",
            indicators=indicators,
            subfields=[pymarc.Subfield("u", "https://example.invalid")],
        ))

    result = structural_replace.apply_structural_find_replace(
        record,
        target_kind="field_tag",
        tag="856",
        match_mode="all",
        find="",
        action="retag",
        destination_tag="956",
        predicate={"ind1": "4", "ind2_not": "0"},
    )

    assert result["changed_fields"] == 1
    assert [field.tag for field in record.fields] == ["856", "956", "856"]


def test_malformed_structural_predicate_fails_before_execution():
    record = _record()
    before = list(record.fields)

    with pytest.raises(ValueError, match="predicate"):
        structural_replace.apply_structural_find_replace(
            record,
            target_kind="field_tag",
            tag="035",
            match_mode="all",
            find="",
            action="retag",
            destination_tag="936",
            predicate={"unknown": True},
        )

    assert record.fields == before


def test_complete_field_signature_requires_exact_indicators_order_and_values():
    record = pymarc.Record()
    exact = pymarc.Field(
        tag="336", indicators=[" ", " "],
        subfields=[pymarc.Subfield("2", "rdacontent"), pymarc.Subfield("a", "text")],
    )
    different_order = pymarc.Field(
        tag="336", indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "text"), pymarc.Subfield("2", "rdacontent")],
    )
    record.add_field(exact)
    record.add_field(different_order)

    structural_replace.apply_structural_find_replace(
        record,
        target_kind="data_field",
        tag="336",
        match_mode="field_signature",
        action="replace_field",
        match_ind1=" ",
        match_ind2=" ",
        match_subfields=[["2", "rdacontent"], ["a", "text"]],
        replacement_ind1=" ",
        replacement_ind2=" ",
        replacement_subfields=[["a", "text"], ["b", "txt"], ["2", "rdacontent"]],
    )

    assert exact not in record.fields
    assert record.fields[0].get_subfields("b") == ["txt"]
    assert record.fields[1] is different_order


@pytest.mark.parametrize(
    "signature_params",
    [
        {"match_ind1": "", "match_ind2": " ", "match_subfields": [["a", "x"]]},
        {"match_ind1": " ", "match_ind2": " ", "match_subfields": [["aa", "x"]]},
        {"match_ind1": " ", "match_ind2": " ", "match_subfields": "bad"},
    ],
)
def test_malformed_complete_field_signatures_fail_before_execution(signature_params):
    errors = structural_replace.validate_request(
        target_kind="data_field",
        tag="336",
        match_mode="field_signature",
        action="replace_field",
        replacement_ind1=" ",
        replacement_ind2=" ",
        replacement_subfields=[["a", "text"]],
        **signature_params,
    )

    assert errors
