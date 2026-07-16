"""Deterministic chunk runner tests for TASK-156."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import db, operation_runner, operations, sandbox


def _mrc_bytes(count: int) -> bytes:
    output = io.BytesIO()
    writer = pymarc.MARCWriter(output)
    for index in range(count):
        record = pymarc.Record()
        record.add_field(pymarc.Field(tag="001", data=str(index + 1)))
        writer.write(record)
    writer.close(close_fh=False)
    return output.getvalue()


def _control_numbers(path: Path) -> list[str]:
    with path.open("rb") as source:
        return [
            record["001"].data
            for record in pymarc.MARCReader(source)
            if record is not None
        ]


@pytest.fixture
def lease(tmp_path: Path) -> operations.Lease:
    input_path = tmp_path / "input.mrc"
    input_path.write_bytes(_mrc_bytes(12))
    request = {
        "tasks": [
            {"name": "first", "body": "record['001'].data += 'A'", "imports": []},
            {"name": "second", "body": "record['001'].data += 'B'", "imports": []},
        ]
    }
    db.init_schema()
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO operations(kind, submitted_by, state, request_json,"
            " total_records, submitted_at)"
            " VALUES ('saved-task-run', 'owner@smith.edu', 'queued', ?, 12, ?)",
            (json.dumps(request), "2026-07-16T12:00:00Z"),
        )
        operation_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO operation_artifacts(operation_id, role, filename,"
            " file_path, record_count, file_bytes, queue_owned, created_at)"
            " VALUES (?, 'input', 'input.mrc', ?, 12, ?, 1, ?)",
            (
                operation_id,
                str(input_path),
                input_path.stat().st_size,
                "2026-07-16T12:00:01Z",
            ),
        )
    claimed = operations.claim_next("worker-a")
    assert claimed is not None
    return claimed


def _copying_sandbox(calls: list[dict], *, errors_by_call=None):
    errors_by_call = errors_by_call or {}

    def run(tasks, *, input_path, **kwargs):
        chunk_count = len(_control_numbers(input_path))
        calls.append({
            "tasks": list(tasks),
            "input_path": input_path,
            "chunk_count": chunk_count,
            **kwargs,
        })
        for processed in range(1, chunk_count + 1):
            kwargs["progress_callback"](processed)
        output_path = kwargs["tmp_dir"] / "output.mrc"
        output_path.write_bytes(input_path.read_bytes())
        errors = errors_by_call.get(len(calls), [])
        return sandbox.SandboxResult(
            output_path=output_path,
            errors=errors,
            error_count=len(errors),
        )

    return run


def test_chunks_preserve_task_order_and_apply_each_task_once(lease, monkeypatch):
    calls = []
    real_sandbox = sandbox.run_tasks_subprocess

    def capture(tasks, **kwargs):
        calls.append([task.name for task in tasks])
        return real_sandbox(tasks, **kwargs)

    monkeypatch.setattr(operation_runner.sandbox, "run_tasks_subprocess", capture)

    outcome = operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert calls == [["first", "second"]] * 3
    assert _control_numbers(outcome.candidate_path) == [
        f"{index}AB" for index in range(1, 13)
    ]
    assert outcome.input_records == outcome.output_records == 12
    assert outcome.changed_records == 12
    json.dumps(outcome.summary)
    assert [
        artifact["role"]
        for artifact in operations.list_artifacts(
            lease.operation_id, "owner@smith.edu"
        )
    ] == ["input"]


def test_every_chunk_gets_its_own_five_minute_limit(lease, monkeypatch):
    calls = []
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox(calls),
    )

    operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert [call["timeout"] for call in calls] == [300, 300, 300]
    assert [call["poll_interval"] for call in calls] == [1.0, 1.0, 1.0]
    assert [call["chunk_count"] for call in calls] == [5, 5, 2]


def test_progress_is_input_wide_and_monotonic(lease, monkeypatch):
    calls = []
    updates = []
    real_renew = operations.renew_lease

    def capture_renew(current_lease, **kwargs):
        if kwargs.get("processed_records") is not None:
            updates.append(kwargs["processed_records"])
        return real_renew(current_lease, **kwargs)

    monkeypatch.setattr(operation_runner.operations, "renew_lease", capture_renew)
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox(calls),
    )

    operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert updates == sorted(updates)
    assert updates[-1] == 12
    assert {1, 5, 6, 10, 11, 12}.issubset(updates)


def test_chunk_errors_use_input_wide_indices(lease, monkeypatch):
    calls = []
    errors = {
        1: [{"index": 3, "code": "transform-failed", "message": "first"}],
        2: [{"index": 3, "code": "transform-failed", "message": "second"}],
    }
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox(calls, errors_by_call=errors),
    )

    outcome = operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert outcome.error_count == 2
    assert [error["index"] for error in outcome.errors] == [3, 8]


def test_cancellation_discards_the_private_aggregate(lease, monkeypatch):
    def cancel_result(tasks, *, tmp_dir, **kwargs):
        return sandbox.SandboxResult(
            output_path=tmp_dir / "output.mrc",
            errors=[],
            cancelled=True,
        )

    monkeypatch.setattr(
        operation_runner.sandbox, "run_tasks_subprocess", cancel_result
    )

    with pytest.raises(operation_runner.OperationCancelled):
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert not (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    ).exists()


def test_cancel_race_during_progress_is_not_reported_as_failure(lease, monkeypatch):
    def cancel_during_progress(tasks, *, tmp_dir, progress_callback, **kwargs):
        operations.request_cancel(lease.operation_id, by="owner@smith.edu")
        progress_callback(1)
        raise AssertionError("progress callback should stop the attempt")

    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        cancel_during_progress,
    )

    with pytest.raises(operation_runner.OperationCancelled):
        operation_runner.run_saved_task_operation(lease, chunk_size=5)


def test_cancellation_during_final_validation_discards_candidate(
    lease, monkeypatch
):
    calls = []
    real_diff = operation_runner.task_diff.compute_task_diff

    def cancel_during_diff(input_path, output_path):
        summary = real_diff(input_path, output_path)
        operations.request_cancel(lease.operation_id, by="owner@smith.edu")
        return summary

    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox(calls),
    )
    monkeypatch.setattr(
        operation_runner.task_diff,
        "compute_task_diff",
        cancel_during_diff,
    )

    with pytest.raises(operation_runner.OperationCancelled):
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert not (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    ).exists()


def test_stale_lease_error_is_not_misclassified_as_user_cancellation(
    lease, monkeypatch
):
    def lose_lease_during_sandbox(
        tasks, *, tmp_dir, cancel_requested, **kwargs
    ):
        with db.connect() as conn:
            conn.execute(
                "UPDATE operations SET lease_token='replacement' WHERE id=?",
                (lease.operation_id,),
            )
        if cancel_requested():
            return sandbox.SandboxResult(
                output_path=tmp_dir / "output.mrc",
                errors=[],
                cancelled=True,
            )
        raise AssertionError("stale lease should stop the sandbox callback")

    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        lose_lease_during_sandbox,
    )
    with pytest.raises(operations.OperationError, match="no longer running"):
        operation_runner.run_saved_task_operation(lease, chunk_size=5)


@pytest.mark.parametrize(
    ("result_kwargs", "code"),
    [
        ({"timed_out": True}, "chunk-timeout"),
        ({"returncode": 2}, "sandbox-exit"),
    ],
)
def test_chunk_process_failures_discard_attempt(
    lease, monkeypatch, result_kwargs, code
):
    def failed_result(tasks, *, tmp_dir, **kwargs):
        output = tmp_dir / "output.mrc"
        output.write_bytes(b"")
        return sandbox.SandboxResult(output_path=output, errors=[], **result_kwargs)

    monkeypatch.setattr(
        operation_runner.sandbox, "run_tasks_subprocess", failed_result
    )

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert raised.value.code == code
    assert not (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    ).exists()


@pytest.mark.parametrize("output_bytes", [b"not marc", _mrc_bytes(4)])
def test_malformed_or_cardinality_changing_chunk_fails(
    lease, monkeypatch, output_bytes
):
    def invalid_output(tasks, *, tmp_dir, **kwargs):
        output = tmp_dir / "output.mrc"
        output.write_bytes(output_bytes)
        return sandbox.SandboxResult(output_path=output, errors=[])

    monkeypatch.setattr(
        operation_runner.sandbox, "run_tasks_subprocess", invalid_output
    )

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert raised.value.code in {"malformed-output", "cardinality-mismatch"}


def test_chunk_configuration_defaults_overrides_and_rejects_invalid(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_QUEUE_CHUNK_RECORDS", raising=False)
    assert operation_runner.queue_chunk_records() == 5000
    monkeypatch.setenv("MARCEDIT_WEB_QUEUE_CHUNK_RECORDS", "7")
    assert operation_runner.queue_chunk_records() == 7
    for value in ("0", "-1", "many"):
        monkeypatch.setenv("MARCEDIT_WEB_QUEUE_CHUNK_RECORDS", value)
        with pytest.raises(operations.OperationError, match="positive integer"):
            operation_runner.queue_chunk_records()


def test_input_corruption_cannot_silently_shrink_the_operation(lease):
    Path(lease.input_artifact["file_path"]).write_bytes(b"not marc")

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert raised.value.code == "malformed-input"


def test_valid_but_incomplete_input_cannot_change_submitted_cardinality(
    lease, monkeypatch
):
    Path(lease.input_artifact["file_path"]).write_bytes(_mrc_bytes(11))
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox([]),
    )

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert raised.value.code == "input-cardinality-mismatch"
