"""Tests for marcedit_web.lib.marcedit_import (.tasksfile conversion).

These focus on the post-Smith-strip behavior: dropped verbs (RDAHELPER,
smith-035-9 buildnewfield) should now degrade to # TODO comments rather
than producing references to deleted helpers.
"""

from __future__ import annotations

import pytest

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


def test_add_with_empty_priority_and_known_condition_is_exact():
    src = "ADD\t877\t\\\\$mMap\t\t/=LDR.{8}[e,f].+/\n"
    result = marcedit_import.convert_tasksfile_text(
        src, name="map", description_fallback=""
    )
    assert result.unsupported == []
    assert "# OP: add-field" in result.body


@pytest.mark.parametrize(
    "line",
    [
        "ADD\t877\t\\\\\t\t",
        "ADD\tbad\t\\\\$mMap\t\t",
        "ADD\t877\t\\\\$!Map\t\t",
        "ADD\t877\t\\\\junk$mMap\t\t",
        "ADD\t877\t\\\\$mMap$\t\t",
    ],
)
def test_structurally_invalid_add_lines_remain_unresolved(line):
    result = marcedit_import.convert_tasksfile_text(
        line + "\n", name="invalid-add", description_fallback=""
    )
    assert result.unsupported == [line.rstrip()]
    assert "# TODO: invalid ADD" in result.body


def test_add_with_unmapped_numeric_priority_remains_blocking():
    src = "ADD\t877\t\\\\$mMap\t106\t/=LDR.{8}[e,f].+/\n"
    result = marcedit_import.convert_tasksfile_text(
        src, name="map", description_fallback=""
    )
    assert result.unsupported == [src.rstrip()]
    assert "unresolved ADD option" in result.body


def test_buildnewfield_flags_remain_visible_and_unresolved():
    line = (
        "buildnewfield\t=876  \\\\$aB({003}){001}-SC$lInternet"
        "\tFalse\tFalse\tTrue\tFalse"
    )
    result = marcedit_import.convert_tasksfile_text(
        line + "\n", name="holdings", description_fallback=""
    )
    assert result.unsupported == [line]
    assert repr(line.split("\t")[1]) in result.body
    assert "recreate with structured Build Field" in result.body


def test_empty_find_subfield_edit_is_unresolved_not_python_replace():
    source = (
        "#DESCRIPTION#Synthetic empty-find safety\n"
        "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0\n"
    )
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="empty-find",
        description_fallback="",
    )

    assert result.unsupported == [
        "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0",
    ]
    assert "sf.value.replace(''," not in result.body
    assert "# OP: custom" in result.body
    assert "empty Find has no proven external meaning" in result.body


def test_unproven_caret_b_subfield_edit_remains_unresolved():
    source = (
        "SUBFIELD_EDIT\t856\tu\t^b\t"
        "http://libproxy.smith.edu/login?url=\t0|0\n"
    )
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="caret-b",
        description_fallback="",
    )
    assert result.unsupported == [
        "SUBFIELD_EDIT\t856\tu\t^b\t"
        "http://libproxy.smith.edu/login?url=\t0|0",
    ]
    assert "unproven external syntax '^b'" in result.body
    assert "sf.value.replace('^b'," not in result.body


def test_nonempty_subfield_edit_keeps_legacy_import_contract():
    source = "SUBFIELD_EDIT\t035\ta\tTFeba\t(SCTFEBA)\t0|0\n"
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="nonempty",
        description_fallback="",
    )
    assert result.unsupported == []
    assert (
        '# OP: subfield-replace {"code": "a", "find": "TFeba", '
        '"replace": "(SCTFEBA)", "tag": "035"}'
    ) in result.body
    assert "sf.value.replace('TFeba', '(SCTFEBA)')" in result.body


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
