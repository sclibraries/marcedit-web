"""Tests for marcedit_web.lib.task_builder (form-builder palette + round-trip)."""

from __future__ import annotations

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
