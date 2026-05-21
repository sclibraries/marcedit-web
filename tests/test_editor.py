"""Tests for marcedit_web.lib.editor (task file round-trip)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import editor


def test_is_valid_slug():
    assert editor.is_valid_slug("strip-oclc-856")
    assert editor.is_valid_slug("5c-eds-cc-core")
    assert not editor.is_valid_slug("With Caps")
    assert not editor.is_valid_slug("")
    assert not editor.is_valid_slug("-leading-dash")


def test_task_file_path_uses_underscores(tmp_path):
    p = editor.task_file_path(tmp_path, "strip-oclc-856")
    assert p == tmp_path / "strip_oclc_856.py"


def test_save_and_parse_round_trip(tmp_path):
    saved = editor.save_user_task(
        tmp_path,
        name="hello",
        description="Greet the world.",
        body='record.add_field(__import__("pymarc").Field(tag="901", data="X"))',
    )
    assert saved.exists()
    parsed = editor.parse_user_task_file(saved)
    assert parsed["name"] == "hello"
    assert parsed["description"] == "Greet the world."
    assert "record.add_field" in parsed["body"]


def test_save_rejects_invalid_slug(tmp_path):
    with pytest.raises(ValueError):
        editor.save_user_task(tmp_path, "Bad Name", "", "pass")


def test_save_rejects_syntax_error(tmp_path):
    with pytest.raises(ValueError, match="syntax"):
        editor.save_user_task(tmp_path, "broken", "", "this is not (")


def test_save_collision_blocks_new_file(tmp_path):
    editor.save_user_task(tmp_path, "hello", "", "pass")
    with pytest.raises(ValueError, match="already exists"):
        editor.save_user_task(tmp_path, "hello", "", "pass")


def test_save_rename_removes_old_file(tmp_path):
    editor.save_user_task(tmp_path, "hello", "", "pass")
    editor.save_user_task(
        tmp_path, "greet", "", "pass", original_name="hello"
    )
    assert (tmp_path / "greet.py").exists()
    assert not (tmp_path / "hello.py").exists()


def test_delete_user_task(tmp_path):
    editor.save_user_task(tmp_path, "hello", "", "pass")
    assert editor.delete_user_task(tmp_path, "hello") is True
    assert editor.delete_user_task(tmp_path, "hello") is False


def test_serialize_uses_new_import_path():
    """Round-trip task files must import from marcedit_web.lib.tasks."""
    text = editor.serialize_user_task("foo", "bar", "pass")
    assert "from marcedit_web.lib.tasks import task" in text


def test_workflow_helpers_are_gone():
    """Workflow round-trip was dropped in Stage 2."""
    for name in (
        "SHIPPED_WORKFLOWS",
        "SHIPPED_TASKS",
        "is_shipped_task",
        "is_shipped_workflow",
        "workflow_file_path",
        "serialize_workflow",
        "save_workflow",
        "delete_workflow",
    ):
        assert not hasattr(editor, name), f"{name} should be gone"
