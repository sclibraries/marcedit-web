"""Tests for the sandbox-backed focused Quick field change runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pymarc import Field, MARCWriter, Record, Subfield

from marcedit_web.lib.record_store import RecordStore
from marcedit_web.lib.quick_field_changes import QuickFieldChangeRequest
from marcedit_web.lib.quick_field_selector import FieldFilter, FieldSelector
from marcedit_web.lib import quick_field_change_runner as runner, sandbox


def _record(*fields: Field) -> Record:
    record = Record()
    record.add_field(Field(tag="001", data="id"))
    for field in fields:
        record.add_field(field)
    return record


def _store(tmp_path: Path, *records: Record) -> RecordStore:
    return RecordStore.from_records(list(records), tmp_dir=tmp_path)


def _delete_request() -> QuickFieldChangeRequest:
    return QuickFieldChangeRequest(
        "delete-field",
        FieldSelector(FieldFilter("856")),
    )


def test_preview_runs_allowlisted_adapter_and_retains_bounded_diff(tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
        _record(Field(tag="245", indicators=["1", "0"], subfields=[Subfield("a", "title")])),
    )

    preview = runner.build_preview(
        store,
        _delete_request(),
        job_file_id=7,
        job_file_version_id=8,
    )

    assert preview.error is None
    assert preview.request_json == json.dumps(
        runner.request_to_payload(_delete_request()),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert preview.record_count == 2
    assert preview.changed_count == 1
    assert preview.unchanged_count == 0
    assert preview.skipped_count == 1
    assert preview.fields_affected == 1
    assert preview.reason_counts == {"no-filtered-fields": 1}
    assert preview.store_id == id(store)
    assert preview.store_revision == store.revision == 0
    assert preview.job_file_id == 7
    assert preview.job_file_version_id == 8
    assert preview.output_path is not None and preview.output_path.is_file()
    assert preview.diff_summary is not None
    assert len(preview.diff_summary.per_record_diffs) == 1


def test_apply_candidate_requires_current_request_and_keeps_store_unchanged(tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    preview = runner.build_preview(store, _delete_request(), job_file_id=1, job_file_version_id=2)
    current = QuickFieldChangeRequest("delete-field", FieldSelector(FieldFilter("245")))

    with pytest.raises(ValueError, match="request changed"):
        runner.build_apply_candidate(
            store,
            preview,
            current,
            job_file_id=1,
            job_file_version_id=2,
        )

    assert store.revision == 0
    assert store.get(0).get("856") is not None


def test_apply_candidate_requires_runner_owned_preview(monkeypatch, tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    request = _delete_request()
    preview = runner.build_preview(store, request)
    monkeypatch.setattr(runner, "artifact_is_owned", lambda _value: False)

    with pytest.raises(ValueError, match="owned"):
        runner.build_apply_candidate(store, preview, request)


def test_apply_candidate_reruns_and_adopt_is_atomic(tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    request = _delete_request()
    preview = runner.build_preview(store, request)
    candidate = runner.build_apply_candidate(store, preview, request)

    assert candidate.changed_count == 1
    assert candidate.skipped_count == 0
    assert store.get(0).get("856") is not None
    runner.adopt_candidate_to_store(store, candidate)
    assert store.get(0).get("856") is None


def test_apply_candidate_rejects_stale_store_and_job_version(tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    request = _delete_request()
    preview = runner.build_preview(store, request, job_file_id=10, job_file_version_id=11)
    store.replace(0, _record(Field(tag="245", indicators=["1", "0"], subfields=[Subfield("a", "changed")])))
    with pytest.raises(ValueError, match="batch changed"):
        runner.build_apply_candidate(store, preview, request, job_file_id=10, job_file_version_id=11)

    current = _store(
        tmp_path / "current",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    current_preview = runner.build_preview(
        current, request, job_file_id=10, job_file_version_id=11
    )
    with pytest.raises(ValueError, match="file changed"):
        runner.build_apply_candidate(
            current,
            current_preview,
            request,
            job_file_id=10,
            job_file_version_id=12,
        )


def test_cleanup_artifact_removes_only_owned_workdir(tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    preview = runner.build_preview(store, _delete_request())
    assert preview.workdir is not None
    owned = preview.workdir
    runner.cleanup_artifact(preview)
    assert not owned.exists()


def test_cleanup_artifact_ignores_foreign_matching_prefix_directory(tmp_path):
    foreign = tmp_path / f"{runner._ARTIFACT_PREFIX}foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("do not remove")

    runner.cleanup_artifact(foreign)

    assert foreign.is_dir()
    assert (foreign / "keep.txt").read_text() == "do not remove"


def test_adopt_rejects_foreign_matching_prefix_candidate(tmp_path):
    store = _store(tmp_path / "store", _record())
    foreign = tmp_path / f"{runner._ARTIFACT_PREFIX}foreign"
    foreign.mkdir()
    output = foreign / "output.mrc"
    store.write_mrc_to(output)
    candidate = runner.QuickFieldChangeCandidate(
        output_path=output,
        workdir=foreign,
        changed_count=0,
        skipped_count=0,
    )

    with pytest.raises(ValueError, match="not owned"):
        runner.adopt_candidate_to_store(store, candidate)
    assert foreign.is_dir()
    assert output.is_file()


def test_apply_candidate_rejects_store_record_count_drift(tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    request = _delete_request()
    preview = runner.build_preview(store, request)
    store.delete(0)

    with pytest.raises(ValueError, match="record count"):
        runner.build_apply_candidate(store, preview, request)


def test_apply_candidate_reruns_adapter_and_does_not_mutate_preview(monkeypatch, tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    request = _delete_request()
    preview = runner.build_preview(store, request)
    assert preview.output_path is not None
    preview_output = preview.output_path
    preview_output.write_bytes(b"sentinel preview artifact")
    preview_counts = (
        preview.changed_count,
        preview.unchanged_count,
        preview.skipped_count,
        preview.fields_affected,
        preview.subfields_affected,
    )
    calls = 0
    real_run = sandbox.run_tasks_subprocess

    def count_runs(tasks, *args, **kwargs):
        nonlocal calls
        calls += 1
        return real_run(list(tasks), *args, **kwargs)

    monkeypatch.setattr(sandbox, "run_tasks_subprocess", count_runs)
    candidate = runner.build_apply_candidate(store, preview, request)

    assert calls == 1
    assert candidate.output_path != preview_output
    assert candidate.output_path.is_file()
    assert RecordStore.from_path(candidate.output_path).get(0).get("856") is None
    assert preview_output.read_bytes() == b"sentinel preview artifact"
    assert preview_counts == (
        preview.changed_count,
        preview.unchanged_count,
        preview.skipped_count,
        preview.fields_affected,
        preview.subfields_affected,
    )


def test_preview_passes_empty_body_and_allowlisted_adapter(monkeypatch, tmp_path):
    store = _store(
        tmp_path / "store",
        _record(Field(tag="856", indicators=["4", "0"], subfields=[Subfield("u", "one")])),
    )
    seen: list[tuple[str, str | None]] = []
    real_run = sandbox.run_tasks_subprocess

    def observe(tasks, *args, **kwargs):
        task = list(tasks)[0]
        seen.append((task.body, task.adapter))
        return real_run([task], *args, **kwargs)

    monkeypatch.setattr(sandbox, "run_tasks_subprocess", observe)
    runner.build_preview(store, _delete_request())

    assert seen == [("", "quick-field-change")]


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("timed_out", "maximum processing time"),
        ("cancelled", "cancelled"),
    ],
)
def test_preview_bounds_terminal_sandbox_status(monkeypatch, tmp_path, status, message):
    store = _store(tmp_path / "store", _record())

    def fake_run(tasks, *, input_path, tmp_dir, **kwargs):
        return sandbox.SandboxResult(
            output_path=Path(tmp_dir) / "output.mrc",
            errors=[],
            returncode=0,
            **{status: True},
        )

    monkeypatch.setattr(sandbox, "run_tasks_subprocess", fake_run)
    preview = runner.build_preview(store, _delete_request())

    assert preview.error is not None
    assert message in preview.error
    assert len(preview.error) <= 1024
    assert preview.output_path is not None


def test_apply_candidate_rejects_child_error_without_mutating_store(monkeypatch, tmp_path):
    store = _store(tmp_path / "store", _record())
    request = _delete_request()
    preview = runner.build_preview(store, request)
    before = store.to_mrc_bytes()

    def fake_run(tasks, *, input_path, tmp_dir, **kwargs):
        return sandbox.SandboxResult(
            output_path=Path(tmp_dir) / "output.mrc",
            errors=[{"message": "x" * 5000}],
            error_count=1,
            returncode=0,
        )

    monkeypatch.setattr(sandbox, "run_tasks_subprocess", fake_run)
    with pytest.raises(ValueError, match="adapter error"):
        runner.build_apply_candidate(store, preview, request)
    assert store.to_mrc_bytes() == before


def test_apply_candidate_rejects_output_cardinality_mismatch(monkeypatch, tmp_path):
    store = _store(tmp_path / "store", _record(), _record())
    request = _delete_request()
    preview = runner.build_preview(store, request)
    real_run = sandbox.run_tasks_subprocess

    def fake_run(tasks, *, input_path, tmp_dir, **kwargs):
        result = real_run(tasks, input_path=input_path, tmp_dir=tmp_dir, **kwargs)
        first = next(RecordStore.from_path(input_path).iter_records())
        with result.output_path.open("wb") as fh:
            MARCWriter(fh).write(first)
        result.adapter_totals = {
            "changed_records": 0,
            "unchanged_records": 2,
            "skipped_records": 0,
            "fields_affected": 0,
            "subfields_affected": 0,
            "reason_codes": {},
        }
        return result

    monkeypatch.setattr(sandbox, "run_tasks_subprocess", fake_run)
    with pytest.raises(ValueError, match="mismatched batch"):
        runner.build_apply_candidate(store, preview, request)


def test_preview_rejects_oversized_canonical_adapter_payload_before_launch(
    monkeypatch, tmp_path,
):
    store = _store(tmp_path / "store", _record())
    request = QuickFieldChangeRequest(
        "add-field",
        destination_tag="245",
        ind1="1",
        ind2="0",
        subfields=tuple(("a", "x" * 1_000) for _ in range(100)),
    )
    monkeypatch.setattr(
        sandbox,
        "run_tasks_subprocess",
        lambda *_args, **_kwargs: pytest.fail("oversized request reached sandbox"),
    )

    preview = runner.build_preview(store, request)

    assert preview.error is not None
    assert "request" in preview.error.lower()
    assert "character" in preview.error.lower() or "byte" in preview.error.lower()


def test_invalid_raw_regex_blocks_preview_for_empty_store(tmp_path):
    store = RecordStore.from_bytes(b"", tmp_dir=tmp_path / "empty")
    request = QuickFieldChangeRequest(
        "delete-field",
        FieldSelector(
            FieldFilter(
                "245",
                subfield_code="a",
                match_mode="raw_regex",
                match_value="[",
            )
        ),
    )

    preview = runner.build_preview(store, request)

    assert preview.error is not None
    assert "regular expression" in preview.error.lower()
