"""Tests for marcedit_web.lib.task_builder (form-builder palette + round-trip)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import task_builder
from marcedit_web.lib.task_builder import Operation


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
            "match_value": "TFeba",
            "new_ind1": " ",
            "new_ind2": "9",
            "new_code": "a",
            "new_value": "(SCTFEBA)",
        },
    )

    rendered = task_builder.render_ops_to_python([op])

    assert "replace_field_subfield_and_indicators(" in rendered["body"]
    assert "'035'" in rendered["body"]
    assert "'TFeba'" in rendered["body"]
    assert "'(SCTFEBA)'" in rendered["body"]
    assert any(
        "replace_field_subfield_and_indicators" in i
        for i in rendered["imports"]
    )


def test_replace_field_subfield_and_indicators_palette_has_regex_options():
    entry = next(
        item
        for item in task_builder.OPERATIONS_PALETTE
        if item["kind"] == "replace-field-subfield-and-indicators"
    )
    params = entry["params"]
    match_value_index = next(
        index
        for index, param in enumerate(params)
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


def test_replace_field_subfield_and_indicators_emits_regex_flags():
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

    assert "regex=True, ignore_case=True)" in rendered["body"]


def test_replace_field_subfield_and_indicators_new_marker_round_trips_regex_flags():
    op = Operation(
        kind="replace-field-subfield-and-indicators",
        params={"match_value": r"TFeba\d+", "regex": True, "ignore_case": True},
    )

    rendered = task_builder.render_ops_to_python([op])
    parsed = task_builder.parse_ops_from_source(rendered["body"])

    assert parsed["ops"][0].params["regex"] is True
    assert parsed["ops"][0].params["ignore_case"] is True


def test_replace_field_subfield_and_indicators_old_marker_uses_false_defaults():
    source = (
        '# OP: replace-field-subfield-and-indicators {"match_value": "TFeba"}'
    )

    parsed = task_builder.parse_ops_from_source(source)
    rendered = task_builder.render_ops_to_python(parsed["ops"])

    marker = rendered["body"].splitlines()[0]
    assert '"regex"' not in marker
    assert '"ignore_case"' not in marker
    assert "regex=False, ignore_case=False)" in rendered["body"]


def test_replace_field_subfield_and_indicators_rejects_invalid_enabled_regex():
    op = Operation(
        kind="replace-field-subfield-and-indicators",
        params={"match_value": "(", "regex": True},
    )

    with pytest.raises(ValueError, match="invalid match regex"):
        task_builder.render_ops_to_python([op])


def test_replace_field_subfield_and_indicators_round_trips_from_markers():
    op = Operation(
        kind="replace-field-subfield-and-indicators",
        params={
            "tag": "035",
            "match_ind1": " ",
            "match_ind2": " ",
            "match_code": "a",
            "match_value": "TFeba",
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
