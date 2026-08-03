"""Tests for deterministic structured Add/Build Field authoring."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from pymarc import Field, MARCReader, Record, Subfield

from marcedit_web.lib import sandbox, task_authoring, task_builder, transforms
from marcedit_web.lib.task_builder import Operation
from marcedit_web.render import task_authoring as task_authoring_render


def _guided_operation(**changes):
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
        "condition": "always",
    }
    params.update(changes)
    return {"kind": "guided-find-replace", "params": params}


def _migration_blocker(**param_changes):
    params = {
        "intent": "Edit control field 001",
        "reason": "Exact external mode is unproven",
        "suggestion": {
            "operation_kind": "set-control-field",
            "prefilled_params": {"tag": "001"},
        },
        "instruction_sha256": "a" * 64,
    }
    params.update(param_changes)
    return {"kind": "migration-blocker", "params": params}


def test_migration_blocker_round_trips_as_inert_marker_and_never_runs():
    blocker = Operation.from_dict(_migration_blocker())

    rendered = task_builder.render_ops_to_python([blocker])
    reopened = task_builder.parse_ops_from_source(rendered["body"])

    assert reopened["ops"][0].to_dict() == blocker.to_dict()
    assert all(
        not line.strip() or line.lstrip().startswith("#") or line.strip() == "pass"
        for line in rendered["body"].splitlines()
    )
    with pytest.raises(ValueError, match="Resolve 1 imported instruction"):
        task_authoring.assert_runnable_operations([blocker.to_dict()])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"intent": "  \n "}, "intent is required"),
        ({"reason": 7}, "reason must be text"),
        ({"suggestion": {"operation_kind": "", "prefilled_params": {}}},
         "suggested operation kind is required"),
        ({
            "suggestion": {
                "operation_kind": "set-control-field",
                "prefilled_params": {"position": float("nan")},
            }
         }, "safe literals"),
        ({"instruction_sha256": "A" * 64}, "instruction digest"),
    ],
)
def test_migration_blocker_validates_user_facing_fields_and_digest(
    change, message
):
    assert any(
        message in error
        for error in task_authoring.validate_operation(
            _migration_blocker(**change)
        )
    )


def test_migration_blocker_normalizes_display_text_without_mutating_input():
    blocker = _migration_blocker(
        intent="  Edit   control\nfield 001  ",
        reason=" Exact external mode\t is unproven ",
    )
    original = copy.deepcopy(blocker)

    normalized = task_authoring.normalize_operation(blocker)

    assert normalized["params"]["intent"] == "Edit control field 001"
    assert normalized["params"]["reason"] == "Exact external mode is unproven"
    assert blocker == original


def test_migration_blocker_explanation_cannot_escape_inert_comments():
    blocker = Operation.from_dict(_migration_blocker(
        intent="Review source\nrecord.remove_fields('001')",
        reason="Confirm mode\nraise RuntimeError('unsafe')",
    ))

    body = task_builder.render_ops_to_python([blocker])["body"]

    assert all(
        line.lstrip().startswith("#") or line.strip() == "pass"
        for line in body.splitlines()
    )


def test_per_operation_preview_rejects_migration_blocker_with_shared_gate():
    with pytest.raises(ValueError, match="Resolve 1 imported instruction"):
        task_authoring.preview_operation(_migration_blocker(), _source_record())


def test_guided_summary_promises_to_keep_both_sides_of_match():
    assert task_authoring.describe_guided_replace(
        _guided_operation()
    ) == (
        "In every 035 subfield a, replace every case-sensitive occurrence "
        "of “TFeba” with “(SCTFEBA)”. Keep text before and after each match."
    )


def test_whole_value_summary_names_destructive_preview_count():
    summary = task_authoring.describe_guided_replace(
        _guided_operation(replacement_mode="whole_value"),
        previewed_discard_count=4,
    )
    assert "discard the complete value" in summary
    assert "4 previewed values" in summary
    assert "the every" not in summary


def test_prepend_with_hidden_matching_state_is_preserved_and_rejected():
    normalized = task_authoring.normalize_guided_replace_operation(
        _guided_operation(
            replacement_mode="prepend",
            match_mode="contains",
            find="stale",
        )
    )
    assert normalized["params"]["match_mode"] == "contains"
    assert normalized["params"]["find"] == "stale"
    assert task_authoring.validate_operation(normalized) == (
        "prepend requires match mode 'none' and an empty Find value.",
    )


def test_unknown_guided_parameter_blocks_lossy_round_trip():
    operation = _guided_operation()
    operation["params"]["future_option"] = True
    assert task_authoring.validate_operation(operation) == (
        "operation parameters contain unexpected keys: future_option",
    )


def test_generic_operation_rejects_non_object_params_without_mutation():
    operation = {"kind": "delete-tag", "params": ["opaque"]}
    original = copy.deepcopy(operation)

    assert task_authoring.validate_operation(operation) == (
        "operation parameters must be an object",
    )
    assert operation == original


def test_guided_operation_without_selected_value_scope_defaults_to_all():
    operation = _guided_operation(replacement_mode="append", match_mode="none", find="")
    del operation["params"]["value_scope"]

    normalized = task_authoring.normalize_guided_replace_operation(operation)

    assert normalized["params"]["value_scope"] == "all"


def test_prepend_append_summary_names_last_value_and_record_order():
    summary = task_authoring.describe_guided_replace(
        _guided_operation(
            replacement_mode="append",
            match_mode="none",
            find="",
            value_scope="last",
        )
    )

    assert "last selected 035 subfield a" in summary
    assert "record order" in summary


def test_guided_operation_editor_normalization_is_lossless():
    operation = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
    )
    assert task_authoring.normalize_operations_for_editor(
        [operation]
    ) == [operation]


def test_raw_operation_validation_does_not_compile_in_parent(
    monkeypatch,
):
    operation = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
    )
    monkeypatch.setattr(
        task_authoring.guided_replace.re,
        "compile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("raw syntax belongs in the sandbox")
        ),
    )

    assert task_authoring.validate_operation(operation) == ()


@pytest.mark.parametrize("field", ["find", "replacement"])
def test_oversized_raw_request_is_rejected_before_syntax_launch(
    monkeypatch, field,
):
    changes = {
        "match_mode": "raw_regex",
        "find": "TFeba",
        "replacement": "replacement",
        field: "x" * 3000,
    }
    operation = _guided_operation(**changes)
    called = []
    monkeypatch.setattr(
        task_authoring.guided_replace_validation,
        "validate_raw_regex",
        lambda **kwargs: called.append(kwargs) or (),
    )

    errors = task_authoring.validate_operation(operation)

    assert any(
        "request" in error.lower() and "limit" in error.lower()
        for error in errors
    )
    assert called == []


def test_deeply_nested_raw_pattern_is_reported_from_sandbox():
    errors = task_authoring.validate_operation(
        _guided_operation(
            match_mode="raw_regex",
            find="(" * 500,
            replacement="x",
        )
    )

    assert len(errors) == 1
    assert "RecursionError" in errors[0]
    assert len(errors[0].encode("utf-8")) <= sandbox.MAX_ERROR_MESSAGE_BYTES


def test_editor_open_retains_raw_sandbox_validation_error(
    monkeypatch,
):
    operation = _guided_operation(
        match_mode="raw_regex",
        find="TFeba",
        replacement="replacement",
    )
    monkeypatch.setattr(
        task_authoring.guided_replace_validation,
        "validate_raw_regex",
        lambda **_kwargs: (
            "Regular expression validation could not start: launcher failed",
        ),
    )

    normalized = task_authoring.normalize_operations_for_editor([operation])

    assert len(normalized) == 1
    assert "launcher failed" in normalized[0]["authoring_error"]


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
def test_historical_todo_comments_do_not_block_without_operation_marker(line):
    assert task_authoring.submission_preflight_issues(line) == ()


def test_submission_preflight_composes_add_build_and_empty_find_issues():
    body = "\n".join(
        [
            '# OP: custom {"code": "# TODO: buildnewfield template \'x\'"}',
            "# TODO: buildnewfield template 'x' — recreate",
            (
                "# OP: subfield-replace "
                '{"code": "y", "find": "", '
                '"replace": "Smith", "tag": "856"}'
            ),
            "pass",
        ]
    )
    issues = task_authoring.submission_preflight_issues(body)
    assert len(issues) == 1
    assert "empty Find" in issues[0]


def test_preflight_does_not_pattern_match_arbitrary_python_source():
    body = "text = \"sf.value.replace('', 'X')\"\npass"
    assert task_authoring.submission_preflight_issues(body) == ()


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


def test_every_palette_required_value_is_validated_before_save_or_run():
    operation = {"kind": "delete-tag", "params": {"tag": ""}}

    assert task_authoring.validate_operation(operation) == (
        "Tag is required",
    )


@pytest.mark.parametrize("unsupported", ["future", ["future"]])
def test_generic_palette_select_rejects_unsupported_value(unsupported):
    operation = {
        "kind": "add-subfield",
        "params": {
            "tag": "245",
            "code": "a",
            "value": "Title",
            "position": unsupported,
        },
    }

    assert task_authoring.validate_operation(operation) == (
        "Position is not supported",
    )


def test_unknown_and_unresolved_operations_need_attention_losslessly():
    unknown = {"kind": "future-operation", "params": {"opaque": 1}}
    unresolved = {
        "kind": "build-field",
        "params": {"subfields": [["a", "literal {name}"]]},
        "authoring_error": "cannot convert literal braces",
    }

    assert task_authoring.validate_operation(unknown) == (
        "operation kind is not supported: future-operation",
    )
    assert task_authoring.validate_operation(unresolved) == (
        "cannot convert literal braces",
    )
    assert unknown["params"] == {"opaque": 1}


def test_submission_preflight_reports_marker_operation_ordinal():
    body = '# OP: delete-tag {"tag":""}\ndelete_tags(record, "")'

    assert task_authoring.submission_preflight_issues(body) == (
        "Operation 1: Tag is required",
    )


def _source_record():
    record = Record()
    record.add_field(Field(tag="001", data="SYNTHETIC12345"))
    record.add_field(Field(tag="003", data="NhCcYBP"))
    record.add_field(
        Field(
            tag="050",
            indicators=[" ", "4"],
            subfields=[Subfield("a", "QA76.9"), Subfield("b", ".A1")],
        )
    )
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


def test_data_subfield_reference_uses_first_matching_value_in_preview():
    operation = {
        "kind": "build-field",
        "params": {
            "tag": "852",
            "ind1": "0",
            "ind2": " ",
            "structured_subfields": [[
                "h",
                [
                    {"type": "data_subfield", "tag": "050", "code": "a"},
                    {"type": "text", "value": " "},
                    {"type": "data_subfield", "tag": "050", "code": "b"},
                ],
            ]],
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
            "condition": "always",
        },
    }

    assert task_authoring.validate_operation(operation) == ()
    assert task_authoring.render_mnemonic(operation) == (
        "=852  0\\$h{050$a} {050$b}"
    )
    assert task_authoring.preview_operation(
        operation, _source_record()
    ).mnemonic == "=852  0\\$hQA76.9 .A1"


def test_data_subfield_reference_compiles_to_same_value_as_preview():
    operation = {
        "kind": "build-field",
        "params": {
            "tag": "856",
            "ind1": "4",
            "ind2": "0",
            "structured_subfields": [[
                "u",
                [
                    {"type": "text", "value": "https://proxy/?url="},
                    {"type": "data_subfield", "tag": "050", "code": "a"},
                ],
            ]],
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
            "condition": "always",
        },
    }
    record = _source_record()
    rendered = task_builder.render_ops_to_python(
        [Operation.from_dict(operation)]
    )
    result = sandbox.run_tasks_subprocess(
        [sandbox.TaskSpec(
            name="data-subfield-preview-equivalence",
            body=rendered["body"],
            imports=rendered["imports"],
        )],
        record.as_marc(),
    )

    assert result.returncode == 0
    with result.output_path.open("rb") as stream:
        output = next(iter(MARCReader(stream)))
    assert output["856"].get_subfields("u") == [
        "https://proxy/?url=QA76.9"
    ]
    assert task_authoring.preview_operation(operation, record).mnemonic == (
        "=856  40$uhttps://proxy/?url=QA76.9"
    )


def test_missing_data_subfield_uses_legacy_missing_control_action_policy():
    operation = {
        "kind": "build-field",
        "params": {
            "tag": "852",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [[
                "h",
                [{"type": "data_subfield", "tag": "050", "code": "z"}],
            ]],
            "existing_field_action": "append",
            "missing_control_action": "fail_record",
            "condition": "always",
        },
    }

    preview = task_authoring.preview_operation(operation, _source_record())

    assert preview.status == "error"
    assert preview.message == "Missing required source value 050 $z."


def test_first_subfield_value_is_deterministically_first_field_first_value():
    record = Record()
    record.add_field(Field(
        tag="035",
        indicators=[" ", " "],
        subfields=[Subfield("a", "first"), Subfield("a", "second")],
    ))
    record.add_field(Field(
        tag="035",
        indicators=[" ", " "],
        subfields=[Subfield("a", "third")],
    ))

    assert task_builder.first_subfield_value(record, "035", "a") == "first"
    assert task_builder.first_subfield_value(record, "035", "z") is None


def test_copy_field_predicate_compiles_as_safe_complete_data_literal():
    operation = {
        "kind": "copy-field",
        "params": {
            "src_tag": "856",
            "dst_tag": "857",
            "predicate": {"subfield_matches": [{
                "code": "3", "mode": "contains", "value": "JSTOR",
                "ignore_case": False,
            }]},
        },
    }

    assert task_authoring.validate_operation(operation) == ()
    assert task_authoring.describe_operation(operation) == (
        "Copy 856 to 857 only when $3 contains JSTOR."
    )
    rendered = task_builder.render_ops_to_python([
        Operation.from_dict(operation)
    ])["body"]
    assert "predicate={'subfield_matches': [{'code': '3'" in rendered
    assert "repr(dict(params))" not in rendered


def test_matched_delete_summary_explains_blank_indicator_and_subfield_exists():
    operation = {
        "kind": "delete-by-subfield",
        "params": {
            "tag": "650",
            "predicate": {
                "ind1": " ",
                "ind2": "6",
                "subfield_matches": [{
                    "code": "a", "mode": "exists", "value": "*",
                    "ignore_case": False,
                }],
            },
        },
    }

    assert task_authoring.describe_operation(operation) == (
        "Delete selected 650 fields only when indicator 1 is blank and "
        "indicator 2 is 6 and $a exists."
    )


def test_copy_field_rejects_predicates_on_control_sources():
    operation = {
        "kind": "copy-field",
        "params": {
            "src_tag": "001",
            "dst_tag": "002",
            "predicate": {"ind1": " "},
        },
    }

    assert task_authoring.validate_operation(operation) == (
        "control fields cannot use indicator or subfield predicates",
    )


def test_copy_field_rejects_crossing_control_and_data_field_shapes():
    operation = {
        "kind": "copy-field",
        "params": {"src_tag": "001", "dst_tag": "035"},
    }

    assert task_authoring.validate_operation(operation) == (
        "source and destination must both be control fields or both be data fields",
    )
    with pytest.raises(ValueError, match="both be control fields or both be data"):
        transforms.copy_field(Record(), "001", "035")


@pytest.mark.parametrize("predicate", [[], False, None])
def test_copy_field_rejects_malformed_falsy_predicates(predicate):
    operation = {
        "kind": "copy-field",
        "params": {
            "src_tag": "856", "dst_tag": "857", "predicate": predicate,
        },
    }

    assert task_authoring.validate_operation(operation) == (
        "field predicate must be an object",
    )
    rendered = task_builder.render_ops_to_python([
        Operation.from_dict(operation)
    ])["body"]
    assert "predicate=" in rendered


def test_field_predicate_controls_preserve_guided_indicator_and_subfield_rows(
    monkeypatch,
):
    params = {
        "predicate": {
            "ind1": "4",
            "ind2_not": "0",
            "subfield_matches": [{
                "code": "3", "mode": "contains", "value": "JSTOR",
                "ignore_case": False,
            }],
        },
    }

    class Input:
        def text_input(self, _label, *, value, **_kwargs):
            return value

        def checkbox(self, _label, *, value, **_kwargs):
            return value

        def selectbox(self, _label, *, options, index, **_kwargs):
            return options[index]

        def button(self, *_args, **_kwargs):
            return False

    control = Input()
    fake_streamlit = SimpleNamespace(
        checkbox=control.checkbox,
        text_input=control.text_input,
        selectbox=control.selectbox,
        button=control.button,
        columns=lambda count: [control] * (count if isinstance(count, int) else len(count)),
        caption=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(task_authoring_render, "st", fake_streamlit)

    task_authoring_render.render_field_predicate_params(
        params, key_prefix="op_0"
    )

    assert params["predicate"] == {
        "ind1": "4",
        "ind2_not": "0",
        "subfield_matches": [{
            "code": "3", "mode": "contains", "value": "JSTOR",
            "ignore_case": False,
        }],
    }


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


@pytest.mark.parametrize(
    "params",
    [
        {"tag": "001", "mode": "value", "value": ""},
        {"tag": "008", "mode": "position", "value": "x", "position": -1},
        {"tag": "008", "mode": "position", "value": "xx", "position": 1},
        {"tag": "008", "mode": "value", "value": "text", "position": 1},
        {"tag": "245", "mode": "value", "value": "text"},
    ],
)
def test_set_control_field_validation_rejects_invalid_requests_before_compile(params):
    errors = task_authoring.validate_operation({
        "kind": "set-control-field",
        "params": {**params, "condition": "always"},
    })

    assert errors


def test_set_control_field_validation_accepts_nonempty_whole_value():
    assert task_authoring.validate_operation({
        "kind": "set-control-field",
        "params": {
            "tag": "001",
            "mode": "value",
            "value": "new",
            "position": None,
            "condition": "always",
        },
    }) == ()
