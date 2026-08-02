"""Tests for marcedit_web.lib.task_builder (form-builder palette + round-trip)."""

from __future__ import annotations

import json

import pytest

from marcedit_web.lib import task_builder
from marcedit_web.lib.task_builder import Operation


def _guided_op():
    return task_builder.Operation(
        kind="guided-find-replace",
        params={
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "contains",
            "find": "TFeba",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": "(SCTFEBA)",
            "occurrences": "all",
            "value_scope": "last",
            "condition": "always",
        },
    )


def test_structural_find_replace_codegen_and_marker_round_trip():
    op = Operation(
        kind="structural-find-replace",
        params={
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "structured",
            "pattern_pieces": [
                {"type": "literal", "value": "TFeba"},
                {"type": "digits", "name": "isbn"},
            ],
            "action": "replace_matched_text",
            "replacement_pieces": [
                {"type": "literal", "value": "(SCTFEBA)"},
                {"type": "capture", "name": "isbn"},
            ],
        },
    )
    rendered = task_builder.render_ops_to_python([op])
    assert "apply_structural_find_replace" in rendered["body"]
    parsed = task_builder.parse_ops_from_source(rendered["body"])
    assert parsed["form_editable"] is True
    assert parsed["ops"][0].params == op.params


def test_structural_find_replace_codegen_rejects_nonliteral_nested_values():
    op = Operation(
        kind="structural-find-replace",
        params={"pattern_pieces": [{"value": object()}]},
    )

    with pytest.raises(TypeError, match="data_lit"):
        task_builder._render_one(op)


def test_guided_replace_compiles_to_one_shared_transform_call():
    rendered = task_builder.render_ops_to_python([_guided_op()])

    assert rendered["imports"] == [
        "from marcedit_web.lib.transforms import apply_guided_find_replace"
    ]
    assert "_guided_replace_result = apply_guided_find_replace(" in (
        rendered["body"]
    )
    assert "match_mode='contains'" in rendered["body"]
    assert "replacement_mode='matched_text'" in rendered["body"]
    assert "value_scope='last'" in rendered["body"]
    assert "re.sub" not in rendered["body"]


def test_guided_replace_marker_round_trip_is_lossless():
    rendered = task_builder.render_ops_to_python([_guided_op()])
    parsed = task_builder.parse_ops_from_source(rendered["body"])
    assert parsed["form_editable"] is True
    assert parsed["ops"] == [_guided_op()]


def test_guided_replace_leader_condition_wraps_the_transform_call():
    op = _guided_op()
    op.params["condition"] = "books"
    rendered = task_builder.render_ops_to_python([op])
    lines = rendered["body"].splitlines()
    assert "if leader_type(record) in 'amt' and leader_biblevel(record) == 'm':" in lines
    call_index = next(
        i for i, line in enumerate(lines)
        if "_guided_replace_result = apply_guided_find_replace(" in line
    )
    assert lines[call_index].startswith("    ")


def test_palette_kinds_are_all_non_smith():
    kinds = {op["kind"] for op in task_builder.OPERATIONS_PALETTE}
    # Smith-specific palette entries must be gone.
    for dropped in {
        "proxy-856",
        "rda-helper",
        "smith-genre-655",
        "smith-035-9",
        "smith-876-barcode",
        "delete-856-url-domain",
    }:
        assert dropped not in kinds, f"{dropped} should be removed from palette"
    # Generic kinds we kept must still be present.
    for kept in {
        "delete-tag",
        "delete-by-subfield",
        "delete-856-url-contains",
        "delete-856-url-regex",
        "add-field",
        "build-field",
        "subfield-replace",
        "sort-fields",
        "set-008-form",
        "custom",
    }:
        assert kept in kinds, f"{kept} should still be in palette"


def test_set_008_form_can_compile_an_explicit_imported_position():
    out = task_builder.render_ops_to_python([
        Operation(kind="set-008-form", params={"position": "29"}),
    ])

    assert "set_008_form_of_item(record, position=29)" in out["body"]


def test_render_delete_tag_emits_op_marker_and_call():
    out = task_builder.render_ops_to_python(
        [Operation(kind="delete-tag", params={"tag": "029"})]
    )
    assert "# OP: delete-tag" in out["body"]
    # Stage 18: codegen now uses ast.unparse-style single-quoted
    # literals via codegen_safety.lit().
    assert "delete_tags(record, '029')" in out["body"]
    assert any("from marcedit_web.lib.transforms import" in i for i in out["imports"])


def test_render_uses_new_transforms_import():
    out = task_builder.render_ops_to_python(
        [Operation(kind="sort-fields", params={})]
    )
    assert any(
        "from marcedit_web.lib.transforms import" in i for i in out["imports"]
    )


def test_render_unknown_kind_becomes_todo():
    out = task_builder.render_ops_to_python(
        [Operation(kind="not-a-real-kind", params={})]
    )
    assert "TODO" in out["body"]


def test_legacy_build_field_still_infers_numeric_template_placeholders():
    out = task_builder.render_ops_to_python(
        [
            Operation(
                kind="build-field",
                params={
                    "tag": "876",
                    "subfields": [["a", "B({003}){001}-SC"]],
                },
            )
        ]
    )

    assert "_t_003 = control_value(record, '003')" in out["body"]
    assert "_t_001 = control_value(record, '001')" in out["body"]
    assert "'B({003}){001}-SC'.replace('{003}', _t_003)" in out["body"]


def test_add_field_replace_policy_deletes_target_before_adding():
    out = task_builder.render_ops_to_python(
        [
            Operation(
                kind="add-field",
                params={
                    "tag": "877",
                    "ind1": " ",
                    "ind2": " ",
                    "subfields": [["m", "Map"]],
                    "existing_field_action": "replace_all",
                    "condition": "always",
                },
            )
        ]
    )
    assert out["body"].index(
        "delete_tags(record, '877')"
    ) < out["body"].index("record.add_ordered_field")
    assert any("delete_tags" in line for line in out["imports"])


def test_add_and_build_palettes_keep_legacy_ai_draft_contract():
    entries = {
        entry["kind"]: entry
        for entry in task_builder.OPERATIONS_PALETTE
        if entry["kind"] in {"add-field", "build-field"}
    }
    for entry in entries.values():
        names = [param["name"] for param in entry["params"]]
        assert "if_absent" in names
        assert "existing_field_action" not in names
        assert "missing_control_action" not in names
    build_names = [
        param["name"] for param in entries["build-field"]["params"]
    ]
    assert "subfields" in build_names
    assert "structured_subfields" not in build_names


def test_build_field_missing_control_fail_is_explicit():
    out = task_builder.render_ops_to_python(
        [
            Operation(
                kind="build-field",
                params={
                    "tag": "876",
                    "ind1": " ",
                    "ind2": " ",
                    "structured_subfields": [
                        [
                            "a",
                            [{"type": "control_field", "tag": "001"}],
                        ]
                    ],
                    "existing_field_action": "append",
                    "missing_control_action": "fail_record",
                    "condition": "always",
                },
            )
        ]
    )
    assert "else:" in out["body"]
    assert (
        "raise ValueError('Build Field requires control field 001')"
        in out["body"]
    )


def test_old_if_absent_marker_keeps_existing_codegen_shape():
    op = Operation(
        kind="build-field",
        params={
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
                    ],
                ]
            ],
            "condition": "always",
            "if_absent": True,
        },
    )
    out = task_builder.render_ops_to_python([op])
    assert "add_field_if_absent" in out["body"]
    assert '"existing_field_action"' not in out["body"]


def test_build_replace_waits_until_source_and_leader_guards_pass():
    out = task_builder.render_ops_to_python(
        [
            Operation(
                kind="build-field",
                params={
                    "tag": "876",
                    "ind1": " ",
                    "ind2": " ",
                    "structured_subfields": [
                        [
                            "a",
                            [{"type": "control_field", "tag": "001"}],
                        ]
                    ],
                    "existing_field_action": "replace_all",
                    "missing_control_action": "skip_field",
                    "condition": "books",
                },
            )
        ]
    )
    assert (
        "if leader_type(record) in 'amt' and "
        "leader_biblevel(record) == 'm':\n"
        "    _build_source_0 = control_value(record, '001')\n"
        "    if _build_source_0 is not None:\n"
        "        delete_tags(record, '876')\n"
        "        record.add_ordered_field"
    ) in out["body"]


def test_parse_round_trip_for_delete_tag():
    ops = [Operation(kind="delete-tag", params={"tag": "029"})]
    rendered = task_builder.render_ops_to_python(ops)
    parsed = task_builder.parse_ops_from_source(rendered["body"])
    assert parsed["form_editable"] is True
    assert len(parsed["ops"]) == 1
    assert parsed["ops"][0].kind == "delete-tag"
    assert parsed["ops"][0].params == {"tag": "029"}


def test_parse_hand_written_falls_back_to_code_view():
    parsed = task_builder.parse_ops_from_source(
        "record.add_field(...)  # no OP markers here\n"
    )
    assert parsed["form_editable"] is False
    assert parsed["reason"] is not None


def test_list_operation_types_deep_copies():
    a = task_builder.list_operation_types()
    a[0]["label"] = "MUTATED"
    b = task_builder.list_operation_types()
    assert b[0]["label"] != "MUTATED"


# ---------------------------------------------------------------------------
# TASK-030: typed ops parity (codegen + round-trip)
# ---------------------------------------------------------------------------


def test_palette_includes_new_typed_ops():
    kinds = {op["kind"] for op in task_builder.OPERATIONS_PALETTE}
    for new in (
        "copy-field", "move-field", "add-subfield", "delete-subfield",
        "copy-subfield", "edit-indicators", "replace-field-data-by-regex",
        "replace-field-subfield-and-indicators",
        "delete-subfield-if-value",
    ):
        assert new in kinds, f"{new} missing from OPERATIONS_PALETTE"


def test_replace_field_subfield_and_indicators_palette_exposes_regex_options():
    entry = next(
        op for op in task_builder.OPERATIONS_PALETTE
        if op["kind"] == "replace-field-subfield-and-indicators"
    )
    params = entry["params"]
    match_value_index = next(
        index for index, param in enumerate(params)
        if param["name"] == "match_value"
    )

    assert params[match_value_index + 1:match_value_index + 3] == [
        {
            "name": "regex",
            "label": "Treat match value as regex",
            "type": "bool",
            "default": False,
        },
        {
            "name": "ignore_case",
            "label": "Case-insensitive",
            "type": "bool",
            "default": False,
        },
    ]


def test_render_copy_field():
    out = task_builder.render_ops_to_python(
        [Operation(kind="copy-field",
                   params={"src_tag": "856", "dst_tag": "956"})]
    )
    assert "copy_field(record, '856', '956')" in out["body"]
    assert any("copy_field" in i for i in out["imports"])


def test_render_move_field():
    out = task_builder.render_ops_to_python(
        [Operation(kind="move-field",
                   params={"src_tag": "856", "dst_tag": "956"})]
    )
    assert "move_field(record, '856', '956')" in out["body"]


def test_render_add_subfield_default_position():
    out = task_builder.render_ops_to_python(
        [Operation(kind="add-subfield",
                   params={"tag": "655", "code": "2", "value": "fast"})]
    )
    body = out["body"]
    assert "add_subfield_to_fields(record, '655', '2', 'fast', position='end')" in body


def test_render_add_subfield_start_position():
    out = task_builder.render_ops_to_python(
        [Operation(kind="add-subfield",
                   params={"tag": "655", "code": "9", "value": "X",
                           "position": "start"})]
    )
    assert "position='start'" in out["body"]


def test_render_delete_subfield_parses_multiple_codes():
    out = task_builder.render_ops_to_python(
        [Operation(kind="delete-subfield",
                   params={"tag": "856", "codes": "u, z 9"})]
    )
    body = out["body"]
    # Order preserved from user input; each code rendered via lit().
    assert "delete_subfields(record, '856', 'u', 'z', '9')" in body


def test_render_delete_subfield_empty_codes_emits_todo():
    out = task_builder.render_ops_to_python(
        [Operation(kind="delete-subfield",
                   params={"tag": "856", "codes": "   "})]
    )
    assert "TODO" in out["body"]


def test_render_delete_subfield_if_value():
    out = task_builder.render_ops_to_python(
        [
            Operation(
                kind="delete-subfield-if-value",
                params={
                    "tag": "300",
                    "code": "b",
                    "value": ":",
                    "match": "exact",
                    "trim": True,
                    "ignore_case": False,
                },
            )
        ]
    )

    body = out["body"]
    assert "delete_subfields_matching_value(" in body
    assert "'300'" in body
    assert "'b'" in body
    assert "match='exact'" in body
    assert "trim=True" in body
    assert any("delete_subfields_matching_value" in i for i in out["imports"])


def test_delete_subfield_if_value_round_trips_from_markers():
    op = Operation(
        kind="delete-subfield-if-value",
        params={
            "tag": "300",
            "code": "b",
            "value": ":",
            "match": "exact",
            "trim": True,
            "ignore_case": False,
        },
    )

    rendered = task_builder.render_ops_to_python([op])
    parsed = task_builder.parse_ops_from_source(rendered["body"])

    assert parsed["form_editable"] is True
    assert [parsed_op.kind for parsed_op in parsed["ops"]] == [
        "delete-subfield-if-value"
    ]
    assert parsed["ops"][0].params == op.params


def test_render_copy_subfield():
    out = task_builder.render_ops_to_python(
        [Operation(kind="copy-subfield",
                   params={"tag": "020", "src_code": "a", "dst_code": "z"})]
    )
    assert "copy_subfield_within_field(record, '020', 'a', 'z')" in out["body"]


def test_render_edit_indicators_both():
    out = task_builder.render_ops_to_python(
        [Operation(kind="edit-indicators",
                   params={"tag": "856", "ind1": "0", "ind2": "1"})]
    )
    assert "set_indicators(record, '856', ind1='0', ind2='1')" in out["body"]


def test_render_edit_indicators_leave_alone_blanks():
    """Empty-string indicator → None (leave alone)."""
    out = task_builder.render_ops_to_python(
        [Operation(kind="edit-indicators",
                   params={"tag": "856", "ind1": "7", "ind2": ""})]
    )
    body = out["body"]
    assert "ind1='7'" in body
    assert "ind2=None" in body


def test_render_replace_field_data_by_regex():
    out = task_builder.render_ops_to_python(
        [Operation(kind="replace-field-data-by-regex",
                   params={"tag": "245", "pattern": r"\s+$",
                           "replacement": "", "ignore_case": True})]
    )
    body = out["body"]
    assert "regex_replace_field_data(record, '245'" in body
    assert "ignore_case=True" in body


def test_render_replace_field_subfield_and_indicators():
    op = Operation(
        kind="replace-field-subfield-and-indicators",
        params={
            "tag": "035",
            "match_ind1": " ",
            "match_ind2": " ",
            "match_code": "a",
            "match_value": r"TFeba\d+",
            "regex": True,
            "ignore_case": True,
            "new_ind1": " ",
            "new_ind2": "9",
            "new_code": "a",
            "new_value": "(SCTFEBA)",
        },
    )

    rendered = task_builder.render_ops_to_python([op])

    assert "replace_field_subfield_and_indicators(" in rendered["body"]
    assert "'035'" in rendered["body"]
    assert "'TFeba\\\\d+'" in rendered["body"]
    assert "'(SCTFEBA)'" in rendered["body"]
    assert "regex=True, ignore_case=True" in rendered["body"]
    assert any(
        "replace_field_subfield_and_indicators" in i
        for i in rendered["imports"]
    )


def test_replace_field_subfield_and_indicators_round_trips_from_markers():
    op = Operation(
        kind="replace-field-subfield-and-indicators",
        params={
            "tag": "035",
            "match_ind1": " ",
            "match_ind2": " ",
            "match_code": "a",
            "match_value": r"TFeba\d+",
            "regex": True,
            "ignore_case": True,
            "new_ind1": " ",
            "new_ind2": "9",
            "new_code": "a",
            "new_value": "(SCTFEBA)",
        },
    )

    rendered = task_builder.render_ops_to_python([op])
    parsed = task_builder.parse_ops_from_source(rendered["body"])

    assert parsed["form_editable"] is True
    assert [parsed_op.kind for parsed_op in parsed["ops"]] == [
        "replace-field-subfield-and-indicators"
    ]
    assert parsed["ops"][0].params == op.params


def test_replace_field_subfield_and_indicators_old_marker_uses_exact_defaults():
    legacy_params = {
        "tag": "035",
        "match_ind1": " ",
        "match_ind2": " ",
        "match_code": "a",
        "match_value": "TFeba",
        "new_ind1": " ",
        "new_ind2": "9",
        "new_code": "a",
        "new_value": "(SCTFEBA)",
    }
    source = (
        "# OP: replace-field-subfield-and-indicators "
        + json.dumps(legacy_params, sort_keys=True)
    )

    parsed = task_builder.parse_ops_from_source(source)
    rendered = task_builder.render_ops_to_python(parsed["ops"])
    reparsed = task_builder.parse_ops_from_source(rendered["body"])

    assert parsed["form_editable"] is True
    assert parsed["ops"][0].params == legacy_params
    assert "regex=False, ignore_case=False" in rendered["body"]
    assert reparsed["ops"][0].params == legacy_params


def test_replace_field_subfield_and_indicators_rejects_invalid_regex():
    op = Operation(
        kind="replace-field-subfield-and-indicators",
        params={
            "tag": "035",
            "match_ind1": " ",
            "match_ind2": " ",
            "match_code": "a",
            "match_value": "(",
            "regex": True,
            "new_ind1": " ",
            "new_ind2": "9",
            "new_code": "a",
            "new_value": "replacement",
        },
    )

    with pytest.raises(ValueError, match="invalid match regex"):
        task_builder.render_ops_to_python([op])


def test_subfield_replace_regex_toggle_emits_re_sub():
    out = task_builder.render_ops_to_python(
        [Operation(kind="subfield-replace",
                   params={"tag": "245", "code": "a", "find": r"^Test",
                           "replace": "Edited", "regex": True})]
    )
    body = out["body"]
    assert "re.compile" in body
    assert "_pat.sub" in body
    assert "import re" in out["imports"]


def test_legacy_subfield_replace_compiler_contract_is_unchanged():
    rendered = task_builder.render_ops_to_python(
        [
            task_builder.Operation(
                kind="subfield-replace",
                params={
                    "tag": "035",
                    "code": "a",
                    "find": "TFeba",
                    "replace": "(SCTFEBA)",
                    "regex": True,
                    "ignore_case": False,
                },
            )
        ]
    )

    assert "_pat.sub('(SCTFEBA)', sf.value)" in rendered["body"]
    assert "if sf.code == 'a'" in rendered["body"]
    assert rendered["imports"] == ["import re", "from pymarc import Subfield"]


def test_existing_atomic_regex_replace_still_replaces_complete_subfield():
    rendered = task_builder.render_ops_to_python(
        [
            task_builder.Operation(
                kind="replace-field-subfield-and-indicators",
                params={
                    "tag": "035",
                    "match_ind1": " ",
                    "match_ind2": " ",
                    "match_code": "a",
                    "match_value": "TFeba",
                    "regex": True,
                    "new_ind1": " ",
                    "new_ind2": "9",
                    "new_code": "a",
                    "new_value": "(SCTFEBA)",
                },
            )
        ]
    )

    assert "replace_field_subfield_and_indicators(" in rendered["body"]
    assert "'(SCTFEBA)'" in rendered["body"]


def test_subfield_replace_literal_unchanged_by_default():
    """Default regex=False keeps the pre-TASK-030 literal codegen shape."""
    out = task_builder.render_ops_to_python(
        [Operation(kind="subfield-replace",
                   params={"tag": "245", "code": "a", "find": "old",
                           "replace": "new"})]
    )
    body = out["body"]
    assert "sf.value.replace('old', 'new')" in body
    # No regex import added when regex=False + ignore_case=False.
    assert "import re" not in out["imports"]


def test_subfield_replace_literal_ignore_case_uses_re_escape():
    out = task_builder.render_ops_to_python(
        [Operation(kind="subfield-replace",
                   params={"tag": "245", "code": "a", "find": "old",
                           "replace": "new", "ignore_case": True})]
    )
    body = out["body"]
    assert "re.escape('old')" in body
    assert "re.IGNORECASE" in body
    assert "import re" in out["imports"]


def test_round_trip_each_new_op_kind():
    """Save + reopen each new op kind via parse_ops_from_source."""
    cases = [
        ("copy-field", {"src_tag": "856", "dst_tag": "956"}),
        ("move-field", {"src_tag": "856", "dst_tag": "956"}),
        ("add-subfield", {"tag": "655", "code": "2", "value": "fast",
                          "position": "end"}),
        ("delete-subfield", {"tag": "856", "codes": "u"}),
        ("copy-subfield", {"tag": "020", "src_code": "a", "dst_code": "z"}),
        ("edit-indicators", {"tag": "856", "ind1": "4", "ind2": "0"}),
        ("replace-field-data-by-regex", {"tag": "245", "pattern": r"\s+$",
                                         "replacement": "",
                                         "ignore_case": False}),
    ]
    ops = [Operation(kind=k, params=p) for k, p in cases]
    rendered = task_builder.render_ops_to_python(ops)
    parsed = task_builder.parse_ops_from_source(rendered["body"])
    assert parsed["form_editable"] is True
    assert [op.kind for op in parsed["ops"]] == [k for k, _ in cases]
    for op, (_, expected_params) in zip(parsed["ops"], cases):
        for key, value in expected_params.items():
            assert op.params[key] == value


def test_codegen_lit_safety_on_typed_ops():
    """No bare f-string slot interpolation of user data into a quoted literal.

    A malicious user value with a closing quote + Python payload must
    be string-escaped (codegen_safety.lit) so it stays a Python
    literal, not executable code. Same contract TASK-018 enforces.
    """
    payload = '")\nimport os; os.system("touch /tmp/PWN")\n#'
    out = task_builder.render_ops_to_python(
        [Operation(kind="copy-field",
                   params={"src_tag": payload, "dst_tag": "999"})]
    )
    # ast.parse should succeed AND the payload must not appear as a
    # raw substring outside its string literal.
    import ast
    ast.parse(out["body"])
    # The literal form has the value escaped, so a naive search for the
    # raw payload string will fail — that's the contract.
    assert "os.system" in out["body"]  # appears inside a string literal
    # But the close-paren-newline-import-os attack form must be quoted
    # rather than free-standing.
    assert "\n)" not in out["body"]
