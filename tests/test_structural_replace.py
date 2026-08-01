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
        match_mode="contains",
        find="",
        action="retag",
        destination_tag="010",
    )
    assert any("same control/data" in error for error in errors)
    assert not structural_replace.validate_request(
        target_kind="tag_range",
        start_tag="001",
        end_tag="009",
        match_mode="contains",
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
