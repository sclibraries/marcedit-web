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


# ---------------------------------------------------------------------------
# Stage 19: archive expansion caps
# ---------------------------------------------------------------------------


def _build_archive(tmp_path, entries):
    """Build a `.task` ZIP with the supplied (name, content) entries."""
    import zipfile

    p = tmp_path / "fixture.task"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return p


def test_convert_task_archive_rejects_over_entry_cap(tmp_path):
    """Past the entries cap, the archive is rejected up front."""
    entries = [(f"task-{i}.txt", "SORTBY\n") for i in range(300)]
    p = _build_archive(tmp_path, entries)
    result = marcedit_import.convert_task_archive(p, max_entries=256)
    assert not result.entries
    assert result.archive_errors
    assert "256" in result.archive_errors[0]


def test_convert_task_archive_rejects_oversize_declared(tmp_path):
    """A zip whose declared sizes blow the cap is rejected pre-decompression."""
    big = "ADD\t999\t\\\\$a" + ("x" * 100_000) + "\n"
    entries = [(f"big-{i}.txt", big) for i in range(20)]  # ~2 MB total
    p = _build_archive(tmp_path, entries)
    result = marcedit_import.convert_task_archive(
        p, max_total_decompressed=500_000  # 0.5 MB
    )
    assert not result.entries
    assert result.archive_errors
    assert "500000" in result.archive_errors[0]


def test_convert_task_archive_within_caps_succeeds(tmp_path):
    """Sanity: a small archive still imports normally."""
    entries = [("solo.txt", "SORTBY\n")]
    p = _build_archive(tmp_path, entries)
    result = marcedit_import.convert_task_archive(p)
    assert result.archive_errors == []
    assert len(result.entries) == 1
    assert result.entries[0].success
