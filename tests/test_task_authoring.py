"""Tests for deterministic structured Add/Build Field authoring."""

from __future__ import annotations

import pytest

from marcedit_web.lib import task_authoring


def test_legacy_build_value_becomes_typed_segments_without_losing_literals():
    assert task_authoring.legacy_value_to_segments(
        "B({003}){001}-SC"
    ) == [
        {"type": "text", "value": "B("},
        {"type": "control_field", "tag": "003"},
        {"type": "text", "value": ")"},
        {"type": "control_field", "tag": "001"},
        {"type": "text", "value": "-SC"},
    ]


def test_literal_braces_are_never_guessed_as_source_references():
    with pytest.raises(
        ValueError,
        match="cannot convert legacy Build Field text losslessly",
    ):
        task_authoring.legacy_value_to_segments("literal {name}")


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({"kind": "add-field", "params": {"tag": "87"}}, "three numeric"),
        ({"kind": "add-field", "params": {"tag": "000"}}, "data fields"),
        (
            {
                "kind": "add-field",
                "params": {
                    "tag": "877",
                    "ind1": "12",
                    "subfields": [["m", "Map"]],
                },
            },
            "indicator 1",
        ),
        (
            {
                "kind": "add-field",
                "params": {
                    "tag": "877",
                    "subfields": [["AA", "Map"]],
                },
            },
            "subfield 1 code",
        ),
        (
            {
                "kind": "add-field",
                "params": {"tag": "877", "subfields": []},
            },
            "at least one subfield",
        ),
        (
            {
                "kind": "build-field",
                "params": {
                    "tag": "876",
                    "structured_subfields": [
                        ["a", [{"type": "control_field", "tag": "245"}]]
                    ],
                },
            },
            "control field 001 through 009",
        ),
    ],
)
def test_invalid_structured_operations_name_the_fault(operation, message):
    assert any(
        message in error
        for error in task_authoring.validate_operation(operation)
    )


def test_existing_if_absent_normalizes_to_identical_field_compatibility():
    normalized = task_authoring.normalize_operation(
        {
            "kind": "build-field",
            "params": {
                "tag": "876",
                "subfields": [["a", "Internet"]],
                "if_absent": True,
            },
        }
    )
    assert normalized["params"]["existing_field_action"] == "skip_if_identical"
    assert normalized["params"]["missing_control_action"] == "skip_field"
    assert normalized["params"]["structured_subfields"] == [
        ["a", [{"type": "text", "value": "Internet"}]]
    ]
    assert "if_absent" not in normalized["params"]
    assert "subfields" not in normalized["params"]


def test_legacy_backslash_indicators_normalize_to_blanks():
    normalized = task_authoring.normalize_operation(
        {
            "kind": "add-field",
            "params": {
                "tag": "877",
                "ind1": "\\",
                "ind2": "\\\\",
                "subfields": [["m", "Map"]],
            },
        }
    )
    assert normalized["params"]["ind1"] == " "
    assert normalized["params"]["ind2"] == " "


def test_unconvertible_legacy_build_stays_visible_in_editor_state():
    original = {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "subfields": [["a", "literal {name}"]],
            "if_absent": False,
        },
    }
    normalized = task_authoring.normalize_operations_for_editor([original])
    assert normalized[0]["params"] == original["params"]
    assert "cannot convert" in normalized[0]["authoring_error"]


@pytest.mark.parametrize(
    "line",
    [
        "# TODO: buildnewfield template '=876  \\\\$a{001}'",
        "# TODO: unresolved ADD option(s); priority='106'",
        "# TODO: ADD with unsupported condition '/unknown/'",
        "# TODO: malformed 'ADD' — ADD",
        "# TODO: malformed 'buildnewfield' — buildnewfield",
    ],
)
def test_only_unresolved_add_build_markers_are_execution_blocking(line):
    assert task_authoring.unresolved_add_build_instructions(line) == (line,)
    assert task_authoring.unresolved_add_build_instructions(
        "# TODO: REPLACE arbitrary regex"
    ) == ()


def test_move_item_preserves_order_and_rejects_out_of_range_moves():
    assert task_authoring.move_item(["a", "b", "c"], 1, -1) == [
        "b", "a", "c"
    ]
    assert task_authoring.move_item(["a", "b"], 0, -1) == ["a", "b"]


def test_blank_subfield_row_names_the_cataloger_action():
    errors = task_authoring.validate_operation(
        {
            "kind": "add-field",
            "params": {
                "tag": "877",
                "subfields": [["", ""]],
            },
        }
    )
    assert "Complete or remove blank subfield row 1" in errors
