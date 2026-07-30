"""Tests for deterministic structured Add/Build Field authoring."""

from __future__ import annotations

import pytest
from pymarc import Field, MARCReader, Record, Subfield

from marcedit_web.lib import sandbox, task_authoring, task_builder
from marcedit_web.lib.task_builder import Operation


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


@pytest.mark.parametrize(
    "condition",
    ["future-condition", "", 0, False, []],
)
def test_unknown_leader_condition_is_rejected_instead_of_becoming_always(
    condition,
):
    operation = {
        "kind": "add-field",
        "params": {
            "tag": "877",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["m", "Map"]],
            "condition": condition,
        },
    }
    assert task_authoring.validate_operation(operation) == (
        "record condition is not supported",
    )
    with pytest.raises(ValueError, match="record condition"):
        task_builder.render_ops_to_python([Operation.from_dict(operation)])


@pytest.mark.parametrize(
    "params",
    [
        {
            "tag": "877",
            "ind1": "12",
            "ind2": " ",
            "subfields": [["m", "Map"]],
        },
        {
            "tag": "877",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["m", "Map"]],
            "existing_field_action": "future-policy",
        },
        {
            "tag": "877",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["m", 42]],
        },
    ],
)
def test_invalid_persisted_add_shapes_stay_raw_and_read_only(params):
    original = {"kind": "add-field", "params": params}
    normalized = task_authoring.normalize_operations_for_editor([original])
    assert normalized[0]["params"] == params
    assert normalized[0]["authoring_error"]


def test_non_mapping_persisted_params_stay_visible_instead_of_crashing():
    original = {"kind": "add-field", "params": ["future", "shape"]}
    normalized = task_authoring.normalize_operations_for_editor([original])
    assert normalized[0]["params"] == original["params"]
    assert "parameters must be an object" in normalized[0]["authoring_error"]


def test_future_build_segment_keys_stay_raw_and_read_only():
    original = {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {
                            "type": "text",
                            "value": "Internet",
                            "future": "preserve-me",
                        }
                    ],
                ]
            ],
        },
    }
    normalized = task_authoring.normalize_operations_for_editor([original])
    assert normalized[0]["params"] == original["params"]
    assert "unexpected keys" in normalized[0]["authoring_error"]


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


def _source_record():
    record = Record()
    record.add_field(Field(tag="001", data="SYNTHETIC12345"))
    record.add_field(Field(tag="003", data="NhCcYBP"))
    return record


def smith_035_operation():
    return {
        "kind": "build-field",
        "params": {
            "tag": "035",
            "ind1": "9",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {"type": "text", "value": "("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                    ],
                ]
            ],
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
            "condition": "always",
        },
    }


def smith_876_operation(missing_control_action="skip_field"):
    return {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {"type": "text", "value": "B("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                        {"type": "text", "value": "-SC"},
                    ],
                ],
                ["l", [{"type": "text", "value": "Internet"}]],
            ],
            "existing_field_action": "append",
            "missing_control_action": missing_control_action,
            "condition": "always",
        },
    }


def _build_operation_with_text(value):
    operation = smith_035_operation()
    operation["params"]["structured_subfields"] = [
        ["a", [{"type": "text", "value": value}]]
    ]
    return operation


def test_035_explanation_and_resolved_preview_agree():
    operation = smith_035_operation()
    assert task_authoring.describe_operation(operation) == (
        "Add an 035 field with indicator 1 “9”, a blank indicator 2, "
        "and subfield a built from 003 and 001. When 035 exists, add "
        "another field. If a source is missing, do not build this field."
    )
    preview = task_authoring.preview_operation(operation, _source_record())
    assert preview.status == "ready"
    assert preview.mnemonic == "=035  9\\$a(NhCcYBP)SYNTHETIC12345"


def test_add_field_explanation_names_values_and_existing_field_action():
    operation = {
        "kind": "add-field",
        "params": {
            "tag": "877",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["m", "Map"]],
            "existing_field_action": "replace_all",
            "missing_control_action": "skip_field",
        },
    }
    assert task_authoring.describe_operation(operation) == (
        "Add an 877 field with a blank indicator 1, a blank indicator 2, "
        "and subfield m containing “Map”. When 877 exists, replace every "
        "field with this tag."
    )


def test_876_preview_keeps_two_subfields_in_order():
    preview = task_authoring.preview_operation(
        smith_876_operation(), _source_record()
    )
    assert preview.mnemonic == (
        "=876  \\\\$aB(NhCcYBP)SYNTHETIC12345-SC$lInternet"
    )


def test_missing_control_preview_obeys_skip_and_fail_policies():
    record = Record()
    record.add_field(Field(tag="001", data="123"))
    skipped = task_authoring.preview_operation(
        smith_876_operation(missing_control_action="skip_field"), record
    )
    failed = task_authoring.preview_operation(
        smith_876_operation(missing_control_action="fail_record"), record
    )
    assert skipped.status == "skipped"
    assert skipped.message == "Missing required control field 003."
    assert failed.status == "error"
    assert failed.message == "Missing required control field 003."


def test_preview_never_mutates_source_record():
    record = _source_record()
    before = record.as_marc()
    task_authoring.preview_operation(smith_035_operation(), record)
    assert record.as_marc() == before


def test_literal_braces_render_as_literals_in_structured_preview():
    operation = _build_operation_with_text("{local}")
    assert "$a{local}" in task_authoring.preview_operation(
        operation, _source_record()
    ).mnemonic


def test_unconvertible_legacy_text_is_presented_without_raising():
    operation = {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["a", "literal {name}"]],
        },
    }
    assert "needs review" in task_authoring.describe_operation(operation)
    assert task_authoring.render_mnemonic(operation) == (
        "=876  \\\\$aliteral {name}"
    )
    assert "cannot convert" in " ".join(
        task_authoring.token_annotations(operation)
    )


def test_legacy_if_absent_preview_does_not_skip_a_different_same_tag_field():
    record = _source_record()
    record.add_field(
        Field(
            tag="876",
            indicators=[" ", " "],
            subfields=[Subfield("a", "Different value")],
        )
    )
    operation = {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["a", "Internet"]],
            "if_absent": True,
        },
    }
    assert task_authoring.preview_operation(operation, record).status == "ready"


def test_legacy_backslash_indicator_matches_execution_blank_indicator():
    record = _source_record()
    record.add_field(
        Field(
            tag="876",
            indicators=[" ", " "],
            subfields=[Subfield("a", "Internet")],
        )
    )
    operation = {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": "\\",
            "ind2": "\\\\",
            "subfields": [["a", "Internet"]],
            "if_absent": True,
        },
    }
    assert task_authoring.preview_operation(
        operation, record
    ).status == "skipped"


def test_876_preview_matches_compiled_sandbox_output():
    record = _source_record()
    operation = smith_876_operation()
    rendered = task_builder.render_ops_to_python(
        [Operation.from_dict(operation)]
    )
    result = sandbox.run_tasks_subprocess(
        [
            sandbox.TaskSpec(
                name="preview-equivalence",
                body=rendered["body"],
                imports=rendered["imports"],
            )
        ],
        record.as_marc(),
    )
    assert result.returncode == 0
    assert result.errors == []
    with result.output_path.open("rb") as stream:
        output = next(iter(MARCReader(stream)))
    assert output["876"].get_subfields("a") == [
        "B(NhCcYBP)SYNTHETIC12345-SC"
    ]
    assert output["876"].get_subfields("l") == ["Internet"]
    assert task_authoring.preview_operation(operation, record).mnemonic == (
        "=876  \\\\$aB(NhCcYBP)SYNTHETIC12345-SC$lInternet"
    )


@pytest.mark.parametrize(
    ("leader_type", "preview_status", "expected_fields"),
    [
        ("e", "ready", 1),
        ("a", "skipped", 0),
    ],
)
def test_conditional_preview_matches_compiled_execution(
    leader_type, preview_status, expected_fields
):
    record = _source_record()
    leader = list(record.leader)
    leader[6] = leader_type
    record.leader = "".join(leader)
    operation = {
        "kind": "add-field",
        "params": {
            "tag": "877",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["m", "Map"]],
            "existing_field_action": "append",
            "condition": "maps",
        },
    }
    preview = task_authoring.preview_operation(operation, record)
    rendered = task_builder.render_ops_to_python(
        [Operation.from_dict(operation)]
    )
    result = sandbox.run_tasks_subprocess(
        [
            sandbox.TaskSpec(
                name="conditional-preview-equivalence",
                body=rendered["body"],
                imports=rendered["imports"],
            )
        ],
        record.as_marc(),
    )
    assert result.returncode == 0
    with result.output_path.open("rb") as stream:
        output = next(iter(MARCReader(stream)))
    assert preview.status == preview_status
    assert len(output.get_fields("877")) == expected_fields


@pytest.mark.parametrize(
    ("leader_type", "drop_003", "preview_status", "expected_fields"),
    [
        ("e", False, "ready", 1),
        ("a", True, "skipped", 0),
    ],
)
def test_conditional_build_preview_checks_condition_before_missing_sources(
    leader_type, drop_003, preview_status, expected_fields
):
    record = _source_record()
    leader = list(record.leader)
    leader[6] = leader_type
    record.leader = "".join(leader)
    if drop_003:
        record.remove_fields("003")
    operation = smith_876_operation()
    operation["params"]["condition"] = "maps"
    preview = task_authoring.preview_operation(operation, record)
    rendered = task_builder.render_ops_to_python(
        [Operation.from_dict(operation)]
    )
    result = sandbox.run_tasks_subprocess(
        [
            sandbox.TaskSpec(
                name="conditional-build-preview-equivalence",
                body=rendered["body"],
                imports=rendered["imports"],
            )
        ],
        record.as_marc(),
    )
    assert result.returncode == 0
    with result.output_path.open("rb") as stream:
        output = next(iter(MARCReader(stream)))
    assert preview.status == preview_status
    assert len(output.get_fields("876")) == expected_fields
    if drop_003:
        assert "does not match" in preview.message
        assert "Missing required control field" not in preview.message


def test_legacy_if_absent_preview_matches_identical_field_execution():
    record = _source_record()
    record.add_field(
        Field(
            tag="876",
            indicators=[" ", " "],
            subfields=[Subfield("a", "Different value")],
        )
    )
    operation = {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["a", "Internet"]],
            "if_absent": True,
        },
    }
    rendered = task_builder.render_ops_to_python(
        [Operation.from_dict(operation)]
    )
    result = sandbox.run_tasks_subprocess(
        [
            sandbox.TaskSpec(
                name="legacy-if-absent-equivalence",
                body=rendered["body"],
                imports=rendered["imports"],
            )
        ],
        record.as_marc(),
    )
    assert result.returncode == 0
    with result.output_path.open("rb") as stream:
        output = next(iter(MARCReader(stream)))
    assert task_authoring.preview_operation(operation, record).status == "ready"
    assert [
        field.get_subfields("a") for field in output.get_fields("876")
    ] == [["Different value"], ["Internet"]]
