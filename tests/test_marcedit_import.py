"""Tests for marcedit_web.lib.marcedit_import (.tasksfile conversion).

These focus on the post-Smith-strip behavior: dropped verbs (RDAHELPER,
smith-035-9 buildnewfield) should now degrade to # TODO comments rather
than producing references to deleted helpers.
"""

from __future__ import annotations

from marcedit_web.lib import marcedit_import


def test_dropped_handlers_are_gone():
    # `RDAHELPER` handler used to dispatch to _emit_rdahelper which called
    # the dropped marc_processing.rda module. With the handler removed the
    # verb falls through to "unsupported".
    assert "RDAHELPER" not in marcedit_import._HANDLERS
    assert not hasattr(marcedit_import, "_emit_rdahelper")


def test_convert_simple_delete():
    src = "DELETE\t029\n"
    result = marcedit_import.convert_tasksfile_text(src, description_fallback="", name="delete-029")
    assert result.name == "delete-029"
    assert "delete_tags" in result.body
    # Import block must point at the new module path.
    assert any(
        "from marcedit_web.lib.transforms import" in i for i in result.imports
    )


def test_convert_unknown_verb_marks_unsupported():
    src = "RDAHELPER\n"
    result = marcedit_import.convert_tasksfile_text(src, description_fallback="", name="rda")
    assert any("RDAHELPER" in line for line in result.unsupported)


def test_build_full_task_file_uses_new_import_path():
    src = "SORTBY\tALL\tTrue\tTrue\n"
    result = marcedit_import.convert_tasksfile_text(src, description_fallback="", name="sortbyall")
    rendered = marcedit_import.build_full_task_file(result)
    assert "from marcedit_web.lib.tasks import task" in rendered
    assert "from marc_processing" not in rendered
