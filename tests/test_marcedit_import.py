"""Tests for marcedit_web.lib.marcedit_import (.tasksfile conversion).

These focus on the post-Smith-strip behavior: dropped verbs (RDAHELPER,
smith-035-9 buildnewfield) should now degrade to # TODO comments rather
than producing references to deleted helpers.
"""

from __future__ import annotations

import pytest

from marcedit_web.lib import marcedit_import, task_authoring


def test_dropped_handlers_are_gone():
    # `RDAHELPER` handler used to dispatch to _emit_rdahelper which called
    # the dropped marc_processing.rda module. With the handler removed the
    # verb falls through to "unsupported".
    assert "RDAHELPER" not in marcedit_import._HANDLERS
    assert not hasattr(marcedit_import, "_emit_rdahelper")


def test_convert_simple_delete():
    src = "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
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


def test_add_with_proven_conditional_policy_is_exact():
    src = "ADD\t877\t\\\\$mMap\t106\t/=LDR.{8}[e,f].+/\n"
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
    assert result.unsupported == [line]
    assert "# OP: migration-blocker" in result.body


def test_add_with_unmapped_numeric_priority_remains_blocking():
    src = "ADD\t877\t\\\\$mMap\t107\t/=LDR.{8}[e,f].+/\n"
    result = marcedit_import.convert_tasksfile_text(
        src, name="map", description_fallback=""
    )
    assert result.unsupported == [src.rstrip()]
    assert "# OP: migration-blocker" in result.body


def test_proven_buildnewfield_flags_convert_to_structured_operation():
    line = (
        "buildnewfield\t=876  \\\\$aB({003}){001}-SC$lInternet"
        "\tFalse\tFalse\tTrue\tFalse"
    )
    result = marcedit_import.convert_tasksfile_text(
        line + "\n", name="holdings", description_fallback=""
    )
    assert result.unsupported == []
    assert result.draft is not None
    assert result.draft.operations[0]["kind"] == "build-field"
    assert "# OP: build-field" in result.body


def test_empty_find_subfield_edit_maps_to_explicit_add_if_missing():
    source = (
        "#DESCRIPTION#Synthetic empty-find safety\n"
        "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0\n"
    )
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="empty-find",
        description_fallback="",
    )

    assert result.unsupported == []
    assert "sf.value.replace(''," not in result.body
    assert "# OP: empty-find-subfield-policy" in result.body
    assert "apply_empty_find_subfield_policy" in result.body
    assert '"policy": "add_if_missing"' in result.body


def test_caret_b_subfield_edit_maps_to_guided_prepend():
    source = (
        "SUBFIELD_EDIT\t856\tu\t^b\t"
        "http://libproxy.smith.edu/login?url=\t0|0\n"
    )
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="caret-b",
        description_fallback="",
    )
    assert result.unsupported == []
    assert "# OP: guided-find-replace" in result.body
    assert '"replacement_mode": "prepend"' in result.body
    assert "sf.value.replace('^b'," not in result.body


def test_unproven_caret_prefixed_subfield_edit_remains_unresolved():
    source = (
        "SUBFIELD_EDIT\t856\tu\t^bhttp://\t"
        "http://libproxy.smith.edu/login?url=\t0|0\n"
    )

    result = marcedit_import.convert_tasksfile_text(
        source,
        name="caret-prefix",
        description_fallback="",
    )

    assert result.unsupported == [source.rstrip("\n")]
    assert "only exact ^b prepend and ^e append caret forms are proven" in result.body


def test_subfield_remove_maps_to_exact_value_deletion():
    source = "SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t107|0\n"

    result = marcedit_import.convert_tasksfile_text(
        source,
        name="remove-035-z",
        description_fallback="",
    )

    assert result.unsupported == []
    assert "# OP: delete-subfield-if-value" in result.body
    assert "delete_subfields_matching_value" in result.body
    assert '"match": "exact"' in result.body
    assert '"trim": false' in result.body


def test_nonempty_subfield_edit_maps_to_guided_contract():
    source = "SUBFIELD_EDIT\t035\ta\tTFeba\t(SCTFEBA)\t0|0\n"
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="nonempty",
        description_fallback="",
    )
    assert result.unsupported == []
    assert '# OP: guided-find-replace' in result.body
    assert '"replacement_mode": "matched_text"' in result.body
    assert "apply_guided_find_replace" in result.body


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


def test_fully_converted_archive_entry_returns_editable_draft(tmp_path):
    source = (
        "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
        "SORTBY\tALL\tTrue\tTrue\n"
    )
    path = _build_archive(tmp_path, [("core.tasksfile.txt", source)])

    result = marcedit_import.convert_task_archive(path)

    entry = result.entries[0]
    assert entry.status == "draft_ready"
    assert entry.task_name == "core-tasksfile"
    assert entry.summary.converted == 2
    assert entry.summary.blocking == 0
    assert [operation["kind"] for operation in entry.operations] == [
        "delete-tag",
        "sort-fields",
    ]
    assert [item.line_number for item in entry.provenance] == [1, 2]
    assert all(item.source_entry == "core.tasksfile.txt" for item in entry.provenance)


def test_partial_archive_entry_preserves_blocker_in_exact_source_order(tmp_path):
    source = (
        "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
        "UNKNOWN\tapparent external intent\n"
        "SORTBY\tALL\tTrue\tTrue\n"
    )
    path = _build_archive(tmp_path, [("mixed.tasksfile.txt", source)])

    result = marcedit_import.convert_task_archive(path)

    entry = result.entries[0]
    assert entry.status == "needs_review"
    assert entry.summary.converted == 2
    assert entry.summary.blocking == 1
    assert [operation["kind"] for operation in entry.operations] == [
        "delete-tag",
        "migration-blocker",
        "sort-fields",
    ]
    with pytest.raises(ValueError, match="Resolve 1 imported instruction"):
        task_authoring.assert_runnable_operations(list(entry.operations))


def test_blocked_archive_entry_does_not_discard_valid_sibling(tmp_path):
    path = _build_archive(tmp_path, [
        ("valid.txt", "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"),
        ("blocked.txt", "UNKNOWN\texternal intent\n"),
    ])

    result = marcedit_import.convert_task_archive(path)

    assert result.archive_errors == []
    assert [entry.status for entry in result.entries] == [
        "draft_ready",
        "needs_review",
    ]
    assert [entry.task_name for entry in result.entries] == ["valid", "blocked"]


def test_text_conversion_uses_registry_for_every_instruction():
    source = (
        "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
        "RDAHELPER\t1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|language of cataloging|0\n"
        "SORTBY\tALL\tTrue\tTrue\n"
    )

    result = marcedit_import.convert_tasksfile_text(
        source,
        name="registry-backed",
        description_fallback="",
    )

    assert result.draft is not None
    assert result.draft.summary.converted == 3
    assert result.unsupported == []
    assert [operation["kind"] for operation in result.draft.operations] == [
        "delete-tag",
        "rda-classify-material",
        "sort-fields",
    ]
    assert result.draft.disclosures == (
        "Smith open equivalent; not a byte-for-byte external emulation",
    )


def test_duplicate_archive_entry_names_remain_distinct_drafts(tmp_path):
    source = "SORTBY\tALL\tTrue\tTrue\n"
    with pytest.warns(UserWarning, match="Duplicate name"):
        path = _build_archive(tmp_path, [
            ("duplicate.txt", source),
            ("duplicate.txt", source),
        ])

    result = marcedit_import.convert_task_archive(path)

    assert result.archive_errors == []
    assert [entry.entry_name for entry in result.entries] == [
        "duplicate.txt",
        "duplicate.txt",
    ]
    assert [entry.status for entry in result.entries] == [
        "draft_ready",
        "draft_ready",
    ]
