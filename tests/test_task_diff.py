"""Tests for marcedit_web.lib.task_diff (post-run diff review)."""

from __future__ import annotations

import io
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import task_diff


def _serialize(records):
    buf = io.BytesIO()
    writer = pymarc.MARCWriter(buf)
    for r in records:
        writer.write(r)
    return buf.getvalue()


def _write(tmp_path, records, name="input.mrc") -> Path:
    p = tmp_path / name
    p.write_bytes(_serialize(records))
    return p


# ---------------------------------------------------------------------------
# Fingerprint fast-path: identical input + output → no changes
# ---------------------------------------------------------------------------


def test_identical_input_and_output_no_changes(tmp_path, make_record):
    """A pass-through task shows zero changed records."""
    records = [make_record() for _ in range(3)]
    in_path = _write(tmp_path, records)
    out_path = _write(tmp_path, records, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path)
    assert summary.total_in == 3
    assert summary.total_out == 3
    assert summary.changed_count == 0
    assert summary.unchanged_count == 3
    assert summary.per_record_diffs == []
    assert summary.cap_triggered is False


def test_diff_streams_both_paths_without_read_bytes(
    tmp_path, make_record, monkeypatch
):
    """A diff must retain only its capped summary, not either MRC blob."""
    input_path = _write(tmp_path, [make_record()], name="before.mrc")
    output_path = _write(tmp_path, [make_record()], name="after.mrc")

    def _read_bytes(self):
        raise AssertionError("task diff must mmap paths instead of reading bytes")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)

    summary = task_diff.compute_task_diff(input_path, output_path)

    assert summary.total_in == 1
    assert summary.total_out == 1


# ---------------------------------------------------------------------------
# Per-tag tally — added / deleted / modified land in the right bucket
# ---------------------------------------------------------------------------


def test_deletion_lands_in_per_tag_deleted(tmp_path, make_record):
    """A task that strips 029 shows up under per_tag_deleted."""
    inputs = [make_record(), make_record()]
    in_path = _write(tmp_path, inputs)

    transformed = []
    for r in inputs:
        clone = pymarc.Record(data=bytes(r.as_marc()))
        # Strip every 029.
        for f in list(clone.get_fields("029")):
            clone.remove_field(f)
        transformed.append(clone)
    out_path = _write(tmp_path, transformed, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path)
    assert summary.changed_count == 2
    assert summary.unchanged_count == 0
    assert summary.per_tag_deleted.get("029") == 2
    assert summary.per_tag_added == {}


def test_addition_lands_in_per_tag_added(tmp_path, make_record):
    """A task adding a new tag shows up under per_tag_added."""
    inputs = [make_record()]
    in_path = _write(tmp_path, inputs)

    transformed = []
    for r in inputs:
        clone = pymarc.Record(data=bytes(r.as_marc()))
        clone.add_ordered_field(pymarc.Field(
            tag="500",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", "Note added by task.")],
        ))
        transformed.append(clone)
    out_path = _write(tmp_path, transformed, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path)
    assert summary.changed_count == 1
    assert summary.per_tag_added.get("500") == 1
    assert summary.per_tag_deleted == {}


def test_modification_lands_in_per_tag_modified(tmp_path, make_record):
    """Changing 245$a → per_tag_modified["245"] increments."""
    inputs = [make_record()]
    in_path = _write(tmp_path, inputs)

    transformed = []
    for r in inputs:
        clone = pymarc.Record(data=bytes(r.as_marc()))
        f245 = clone.get_fields("245")[0]
        f245.subfields = [pymarc.Subfield("a", "Edited title.")]
        transformed.append(clone)
    out_path = _write(tmp_path, transformed, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path)
    assert summary.changed_count == 1
    assert summary.per_tag_modified.get("245") == 1


# ---------------------------------------------------------------------------
# Per-record drill-down structure + cap
# ---------------------------------------------------------------------------


def test_per_record_diffs_capture_001_identifier(tmp_path, make_record):
    """The identifier on each diff entry is the 001 value."""
    inputs = [make_record()]
    inputs[0].remove_fields("001")
    inputs[0].add_field(pymarc.Field(tag="001", data="REC-99"))
    in_path = _write(tmp_path, inputs)

    transformed = []
    for r in inputs:
        clone = pymarc.Record(data=bytes(r.as_marc()))
        for f in list(clone.get_fields("029")):
            clone.remove_field(f)
        transformed.append(clone)
    out_path = _write(tmp_path, transformed, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path)
    assert len(summary.per_record_diffs) == 1
    assert summary.per_record_diffs[0].identifier == "REC-99"
    assert summary.per_record_diffs[0].record_index == 0


def test_per_record_cap_triggered_for_large_change_set(tmp_path, make_record):
    """With diff_cap=3 and 5 changed records, cap_triggered = True."""
    inputs = [make_record() for _ in range(5)]
    in_path = _write(tmp_path, inputs)

    transformed = []
    for r in inputs:
        clone = pymarc.Record(data=bytes(r.as_marc()))
        for f in list(clone.get_fields("029")):
            clone.remove_field(f)
        transformed.append(clone)
    out_path = _write(tmp_path, transformed, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path, diff_cap=3)
    assert summary.changed_count == 5
    assert len(summary.per_record_diffs) == 3
    assert summary.cap_triggered is True


def test_diff_rows_have_recognizable_statuses(tmp_path, make_record):
    """The aligned diff includes added/removed/unchanged rows."""
    inputs = [make_record()]
    in_path = _write(tmp_path, inputs)

    transformed = []
    for r in inputs:
        clone = pymarc.Record(data=bytes(r.as_marc()))
        for f in list(clone.get_fields("029")):
            clone.remove_field(f)
        transformed.append(clone)
    out_path = _write(tmp_path, transformed, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path)
    diff = summary.per_record_diffs[0]
    statuses = {status for _, _, status in diff.rows}
    assert "removed" in statuses
    assert "unchanged" in statuses


# ---------------------------------------------------------------------------
# Mixed batch — some changed, some not
# ---------------------------------------------------------------------------


def test_mixed_batch_partitions_changed_vs_unchanged(tmp_path, make_record):
    """Three records, only the middle one is modified."""
    inputs = [make_record(), make_record(), make_record()]
    in_path = _write(tmp_path, inputs)

    transformed = []
    for idx, r in enumerate(inputs):
        clone = pymarc.Record(data=bytes(r.as_marc()))
        if idx == 1:
            for f in list(clone.get_fields("029")):
                clone.remove_field(f)
        transformed.append(clone)
    out_path = _write(tmp_path, transformed, name="output.mrc")

    summary = task_diff.compute_task_diff(in_path, out_path)
    assert summary.total_in == 3
    assert summary.changed_count == 1
    assert summary.unchanged_count == 2
    assert summary.per_record_diffs[0].record_index == 1


def test_empty_inputs_and_outputs_are_safe(tmp_path):
    """Edge: empty MRC on both sides returns an empty summary."""
    in_path = tmp_path / "empty.mrc"
    in_path.write_bytes(b"")
    out_path = tmp_path / "empty-output.mrc"
    out_path.write_bytes(b"")
    summary = task_diff.compute_task_diff(in_path, out_path)
    assert summary.total_in == 0
    assert summary.total_out == 0
    assert summary.changed_count == 0
