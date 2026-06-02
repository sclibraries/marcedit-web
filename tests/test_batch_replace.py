"""Tests for marcedit_web.lib.batch_replace (TASK-036)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import batch_replace as br
from marcedit_web.lib.batch_replace import (
    BatchReplaceRequest,
    apply_preview,
    build_preview,
    fingerprint_record,
    matched_indices_for,
    validate_request,
)
from marcedit_web.lib.record_store import RecordStore


pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="build_preview spawns the POSIX sandbox subprocess.",
)


@pytest.fixture
def store(tmp_path, make_record) -> RecordStore:
    """Synthetic 3-record store with predictable 245$a values.

    The ``make_record`` factory from conftest yields records with
    ``245$a = "Test title."``, which gives the matching tests a
    stable needle independent of the real cataloging fixture.
    """
    records = [make_record() for _ in range(3)]
    return RecordStore.from_records(
        records,
        tmp_dir=tmp_path / "rs",
        filename="synthetic.mrc",
    )


def _make_request(**kwargs) -> BatchReplaceRequest:
    base = dict(
        tag="245", subfield="a",
        find="title", replace="title",
        regex=False, ignore_case=False,
    )
    base.update(kwargs)
    return BatchReplaceRequest(**base)


# ---------------------------------------------------------------------------
# validate_request
# ---------------------------------------------------------------------------


def test_validate_request_empty_tag_rejected():
    req = _make_request(tag="")
    assert validate_request(req) and "Tag is required" in validate_request(req)


def test_validate_request_empty_find_rejected():
    req = _make_request(find="")
    assert "Find text" in validate_request(req)


def test_validate_request_bad_regex_rejected():
    req = _make_request(find="(unbalanced", regex=True)
    err = validate_request(req)
    assert err and "Invalid regex" in err


def test_validate_request_multichar_subfield_rejected():
    req = _make_request(subfield="ab")
    assert "single character" in validate_request(req)


def test_validate_request_happy_path_returns_none():
    assert validate_request(_make_request()) is None


# ---------------------------------------------------------------------------
# matched_indices_for
# ---------------------------------------------------------------------------


def test_matched_indices_for_literal_match_finds_records(store):
    """Every fixture record has 245$a containing 'Test title.' so all match."""
    req = _make_request(tag="245", subfield="a", find="Test title")
    matched = matched_indices_for(store, req)
    assert matched == list(range(store.count()))


def test_matched_indices_for_no_match_returns_empty(store):
    req = _make_request(find="Bogus value that no record has")
    assert matched_indices_for(store, req) == []


def test_matched_indices_for_ignore_case(store):
    """Lowercased find still matches a Title-cased subfield value."""
    case_sensitive = _make_request(find="test title")
    assert matched_indices_for(store, case_sensitive) == []
    case_insensitive = _make_request(find="test title", ignore_case=True)
    assert matched_indices_for(store, case_insensitive) == list(range(store.count()))


def test_matched_indices_for_regex(store):
    """Regex find narrows to records whose 245$a matches a pattern."""
    req = _make_request(find=r"^Test\b", regex=True)
    matched = matched_indices_for(store, req)
    assert matched == list(range(store.count()))


def test_matched_indices_for_subfield_specific(store):
    """Subfield filter only matches the given subfield, not arbitrary ones."""
    # Fixture's 245 has 'Test title.' on $a; nothing on $z.
    req_a = _make_request(tag="245", subfield="a", find="Test")
    req_z = _make_request(tag="245", subfield="z", find="Test")
    assert matched_indices_for(store, req_a) == list(range(store.count()))
    assert matched_indices_for(store, req_z) == []


def test_matched_indices_for_unknown_tag_returns_empty(store):
    req = _make_request(tag="999", find="anything")
    assert matched_indices_for(store, req) == []


# ---------------------------------------------------------------------------
# build_preview — end-to-end through the sandbox
# ---------------------------------------------------------------------------


def test_build_preview_empty_match_returns_empty_preview(store):
    req = _make_request(find="never-appears-anywhere")
    preview = build_preview(store, req)
    assert preview.is_empty
    assert preview.matched_indices == []
    assert preview.changed_count == 0


def test_build_preview_invalid_request_raises():
    req = _make_request(find="(", regex=True)
    with pytest.raises(ValueError) as exc:
        build_preview(None, req)  # store not reached
    assert "Invalid regex" in str(exc.value)


def test_build_preview_literal_replace_changes_records(store):
    """Replace 'Test title.' → 'Modified title.' in 245$a; preview shows changes."""
    req = _make_request(find="Test title.", replace="Modified title.")
    preview = build_preview(store, req)
    assert preview.error is None, preview.error
    assert preview.matched_indices == list(range(store.count()))
    assert preview.changed_count == store.count()
    # The output records have the new value in 245$a.
    for rec in preview.output_records:
        assert rec.get_fields("245")[0]["a"] == "Modified title."


def test_build_preview_does_not_mutate_store(store):
    """Preview is non-mutating — original store is unchanged."""
    before = [r.get("245")["a"] for r in list(store.iter_records())]
    build_preview(store, _make_request(find="Test", replace="Edited"))
    after = [r.get("245")["a"] for r in list(store.iter_records())]
    assert before == after


def test_build_preview_regex_field_data_path(store):
    """No subfield filter → uses replace-field-data-by-regex under the hood."""
    req = _make_request(
        tag="245", subfield=None,
        find=r"\bTest\b", replace="Edited",
        regex=True,
    )
    preview = build_preview(store, req)
    assert preview.error is None
    assert preview.changed_count > 0


# ---------------------------------------------------------------------------
# apply_preview
# ---------------------------------------------------------------------------


def test_apply_preview_commits_changes(store):
    """Apply writes the output records back to the store at matched indices."""
    req = _make_request(find="Test title.", replace="Applied title.")
    preview = build_preview(store, req)
    result = apply_preview(store, preview)
    assert result.applied
    assert result.applied_indices == list(range(store.count()))
    # Live store now reflects the replacement.
    for rec in store.iter_records():
        assert rec.get("245")["a"] == "Applied title."


def test_apply_preview_refuses_stale(store):
    """If a matched record changes between preview and apply, refuse."""
    req = _make_request(find="Test title.", replace="Stale-test title.")
    preview = build_preview(store, req)
    assert preview.matched_indices, "fixture should produce matches"

    # Mutate the first matched record to simulate an external edit.
    idx = preview.matched_indices[0]
    record = store.get(idx)
    record.remove_fields("245")
    record.add_field(pymarc.Field(
        tag="245",
        indicators=["1", "0"],
        subfields=[pymarc.Subfield("a", "External edit.")],
    ))
    store.replace(idx, record)

    result = apply_preview(store, preview)
    assert not result.applied
    assert idx in result.stale_indices
    assert "Stale preview" in (result.error or "")
    # No other records were mutated by apply.
    other_idx = preview.matched_indices[1]
    assert "Stale-test" not in store.get(other_idx).get("245")["a"]


def test_apply_preview_refuses_empty_match():
    """Applying an empty preview is a guard-rail error, not a no-op."""
    preview = br.BatchReplacePreview(
        request=_make_request(),
        matched_indices=[],
        fingerprints={},
    )
    result = apply_preview(None, preview)
    assert "No matched records" in (result.error or "")


def test_apply_preview_refuses_preview_in_error_state():
    """A preview with a sandbox/parsing error blocks apply with a clear message."""
    preview = br.BatchReplacePreview(
        request=_make_request(),
        matched_indices=[0],
        fingerprints={0: "deadbeef"},
        error="Sandbox returned 17 records for 1 matched input",
    )
    result = apply_preview(None, preview)
    assert "Preview is in error state" in (result.error or "")


# ---------------------------------------------------------------------------
# fingerprint_record stability
# ---------------------------------------------------------------------------


def test_fingerprint_record_stable_for_same_bytes(make_record):
    """Same record bytes → same fingerprint."""
    rec_a = make_record()
    rec_b = make_record()
    assert fingerprint_record(rec_a) == fingerprint_record(rec_b)


def test_fingerprint_record_changes_when_record_changes(make_record):
    rec = make_record()
    before = fingerprint_record(rec)
    rec.remove_fields("245")
    rec.add_field(pymarc.Field(
        tag="245",
        indicators=["1", "0"],
        subfields=[pymarc.Subfield("a", "Changed.")],
    ))
    after = fingerprint_record(rec)
    assert before != after


# ---------------------------------------------------------------------------
# TASK-046: preview cap + batch-identity drift
# ---------------------------------------------------------------------------


def test_preview_records_batch_identity(store):
    """build_preview snapshots (filename, count) on the preview."""
    preview = build_preview(
        store, _make_request(find="Test title.", replace="X"),
    )
    assert preview.batch_identity == ("synthetic.mrc", store.count())


def test_apply_refuses_when_batch_identity_drifts(store, tmp_path, make_record):
    """Loading a different store between preview and apply → refused."""
    preview = build_preview(
        store, _make_request(find="Test title.", replace="Drift-test"),
    )
    assert preview.matched_indices

    # Build a different store (different filename) and try to Apply
    # the preview against it — the identity check must fire BEFORE
    # the fingerprint check.
    other = RecordStore.from_records(
        [make_record() for _ in range(2)],
        tmp_dir=tmp_path / "other",
        filename="OTHER.mrc",
    )
    result = apply_preview(other, preview)
    assert not result.applied
    assert "Batch changed" in (result.error or "")


def test_preview_cap_triggered_for_large_match_set(monkeypatch, tmp_path, make_record):
    """When matched > MAX_PREVIEW_MATCHES, sandbox only runs the first N."""
    # Shrink the cap so we don't have to build a 500-record fixture.
    monkeypatch.setattr(br, "MAX_PREVIEW_MATCHES", 3)
    records = [make_record() for _ in range(7)]
    store = RecordStore.from_records(
        records, tmp_dir=tmp_path / "cap", filename="cap.mrc",
    )

    preview = build_preview(
        store, _make_request(find="Test title.", replace="Edited"),
    )
    assert preview.error is None
    assert len(preview.matched_indices) == 7
    assert preview.preview_cap_triggered is True
    # output_records is the SUBSET (cap-sized), not the full match list.
    assert len(preview.output_records) == 3
    # diff_summary covers the subset.
    assert preview.changed_count <= 3


def test_apply_with_capped_preview_runs_sandbox_over_full_set(
    monkeypatch, tmp_path, make_record,
):
    """Capped preview → Apply re-runs sandbox and commits to ALL matched indices."""
    monkeypatch.setattr(br, "MAX_PREVIEW_MATCHES", 3)
    records = [make_record() for _ in range(7)]
    store = RecordStore.from_records(
        records, tmp_dir=tmp_path / "cap", filename="cap.mrc",
    )

    preview = build_preview(
        store, _make_request(find="Test title.", replace="Applied"),
    )
    assert preview.preview_cap_triggered is True

    result = apply_preview(store, preview)
    assert result.applied
    assert len(result.applied_indices) == 7  # full matched set committed
    # Every live record in the store carries the new value.
    for rec in store.iter_records():
        assert rec.get("245")["a"] == "Applied"
