"""Deterministic chunk runner tests for TASK-156."""

from __future__ import annotations

import dataclasses
import io
import json
import shutil
import threading
import time
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
        "version": 1,
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


def test_exact_error_count_survives_global_detail_cap(lease, monkeypatch):
    calls = []

    def many_errors(tasks, *, input_path, tmp_dir, progress_callback, **kwargs):
        chunk_count = len(_control_numbers(input_path))
        calls.append(chunk_count)
        progress_callback(chunk_count)
        output = tmp_dir / "output.mrc"
        output.write_bytes(input_path.read_bytes())
        return sandbox.SandboxResult(
            output_path=output,
            error_count=500,
            errors=[
                {
                    "index": (index % chunk_count) + 1,
                    "code": "transform-failed",
                    "message": str(index),
                }
                for index in range(150)
            ],
        )

    monkeypatch.setattr(
        operation_runner.sandbox, "run_tasks_subprocess", many_errors
    )

    outcome = operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert calls == [5, 5, 2]
    assert outcome.error_count == 1500
    assert len(outcome.errors) == sandbox.MAX_RETAINED_ERRORS
    assert outcome.errors[0]["index"] == 1
    assert outcome.errors[150]["index"] == 6


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


@pytest.mark.parametrize("version", [None, 2, "1"])
def test_runner_rejects_missing_or_unknown_request_versions(lease, version):
    request = dict(lease.request)
    if version is None:
        request.pop("version")
    else:
        request["version"] = version
    invalid = dataclasses.replace(lease, request=request)

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(invalid, chunk_size=5)

    assert raised.value.code == "unsupported-request-version"
    assert str(raised.value) == "Operation request version is not supported."


def test_runner_rejects_an_empty_task_snapshot(lease):
    invalid = dataclasses.replace(
        lease,
        request={"version": 1, "tasks": []},
    )

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(invalid, chunk_size=5)

    assert raised.value.code == "invalid-request"
    assert str(raised.value) == "Operation must include at least one task."


def test_lease_heartbeat_runs_while_chunk_input_is_being_created(
    lease, monkeypatch
):
    heartbeat_seen = threading.Event()
    real_renew = operations.renew_lease
    real_write_chunk = operation_runner._write_chunk

    def capture_renew(current_lease, **kwargs):
        result = real_renew(current_lease, **kwargs)
        if threading.current_thread().name == "operation-lease-heartbeat":
            heartbeat_seen.set()
        return result

    def blocked_write_chunk(reader, path, limit):
        assert heartbeat_seen.wait(1)
        return real_write_chunk(reader, path, limit)

    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(operation_runner.operations, "renew_lease", capture_renew)
    monkeypatch.setattr(operation_runner, "_write_chunk", blocked_write_chunk)
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox([]),
    )

    outcome = operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert outcome.output_records == 12
    assert heartbeat_seen.is_set()


def test_lease_heartbeat_starts_before_existing_attempt_cleanup(
    lease, monkeypatch
):
    attempt_dir = (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    )
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "stale").write_text("old attempt")
    heartbeat_seen = threading.Event()
    real_renew = operations.renew_lease
    real_rmtree = shutil.rmtree

    def capture_renew(current_lease, **kwargs):
        result = real_renew(current_lease, **kwargs)
        if threading.current_thread().name == "operation-lease-heartbeat":
            heartbeat_seen.set()
        return result

    def blocked_rmtree(path, *args, **kwargs):
        if Path(path) == attempt_dir:
            assert heartbeat_seen.wait(1)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(operation_runner.operations, "renew_lease", capture_renew)
    monkeypatch.setattr(operation_runner.shutil, "rmtree", blocked_rmtree)
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox([]),
    )

    outcome = operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert outcome.output_records == 12
    assert heartbeat_seen.is_set()


def test_lease_heartbeat_runs_during_final_diff_validation(lease, monkeypatch):
    heartbeat_seen = threading.Event()
    validation_started = threading.Event()
    real_renew = operations.renew_lease
    real_diff = operation_runner.task_diff.compute_task_diff

    def capture_renew(current_lease, **kwargs):
        result = real_renew(current_lease, **kwargs)
        if (
            threading.current_thread().name == "operation-lease-heartbeat"
            and validation_started.is_set()
        ):
            heartbeat_seen.set()
        return result

    def blocked_diff(input_path, output_path):
        validation_started.set()
        assert heartbeat_seen.wait(1)
        return real_diff(input_path, output_path)

    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(operation_runner.operations, "renew_lease", capture_renew)
    monkeypatch.setattr(
        operation_runner.task_diff, "compute_task_diff", blocked_diff
    )
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox([]),
    )

    outcome = operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert outcome.output_records == 12
    assert heartbeat_seen.is_set()


def test_heartbeat_ownership_failure_propagates_and_cleans_attempt(
    lease, monkeypatch
):
    heartbeat_failed = threading.Event()
    real_renew = operations.renew_lease
    real_write_chunk = operation_runner._write_chunk

    def fail_heartbeat(current_lease, **kwargs):
        if threading.current_thread().name == "operation-lease-heartbeat":
            heartbeat_failed.set()
            raise operations.OperationError("operation is no longer running")
        return real_renew(current_lease, **kwargs)

    def blocked_write_chunk(reader, path, limit):
        assert heartbeat_failed.wait(1)
        return real_write_chunk(reader, path, limit)

    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(operation_runner.operations, "renew_lease", fail_heartbeat)
    monkeypatch.setattr(operation_runner, "_write_chunk", blocked_write_chunk)

    with pytest.raises(operations.OperationError, match="no longer running"):
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert not (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    ).exists()


@pytest.mark.parametrize("cancel", [False, True], ids=["failure", "cancel"])
def test_shutdown_rechecks_heartbeat_before_returning_candidate(
    lease, monkeypatch, cancel
):
    shutdown_window = threading.Event()
    heartbeat_entered = threading.Event()
    release_heartbeat = threading.Event()
    real_renew = operations.renew_lease
    real_asdict = operation_runner.asdict

    def fail_during_shutdown(current_lease, **kwargs):
        if (
            threading.current_thread().name == "operation-lease-heartbeat"
            and shutdown_window.is_set()
        ):
            heartbeat_entered.set()
            assert release_heartbeat.wait(1)
            if cancel:
                operations.request_cancel(
                    lease.operation_id, by="owner@smith.edu"
                )
                return real_renew(current_lease, **kwargs)
            raise operations.OperationError("operation is no longer running")
        return real_renew(current_lease, **kwargs)

    def synchronize_outcome(value):
        shutdown_window.set()
        assert heartbeat_entered.wait(1)
        release_heartbeat.set()
        return real_asdict(value)

    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(operation_runner.operations, "renew_lease", fail_during_shutdown)
    monkeypatch.setattr(operation_runner, "asdict", synchronize_outcome)
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox([]),
    )

    expected = (
        operation_runner.OperationCancelled
        if cancel
        else operations.OperationError
    )
    with pytest.raises(expected):
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert not (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    ).exists()


def test_blocked_heartbeat_shutdown_is_bounded_and_reported(lease, monkeypatch):
    shutdown_window = threading.Event()
    heartbeat_entered = threading.Event()
    release_heartbeat = threading.Event()
    shutdown_started = []
    real_renew = operations.renew_lease
    real_asdict = operation_runner.asdict

    def block_during_shutdown(current_lease, **kwargs):
        if (
            threading.current_thread().name == "operation-lease-heartbeat"
            and shutdown_window.is_set()
        ):
            heartbeat_entered.set()
            release_heartbeat.wait(1)
            raise operations.OperationError("operation is no longer running")
        return real_renew(current_lease, **kwargs)

    def synchronize_outcome(value):
        shutdown_started.append(time.monotonic())
        shutdown_window.set()
        assert heartbeat_entered.wait(1)
        return real_asdict(value)

    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_STOP_SECONDS", 0.05)
    monkeypatch.setattr(operation_runner.operations, "renew_lease", block_during_shutdown)
    monkeypatch.setattr(operation_runner, "asdict", synchronize_outcome)
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        _copying_sandbox([]),
    )

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)
    elapsed = time.monotonic() - shutdown_started[0]
    release_heartbeat.set()
    for thread in threading.enumerate():
        if thread.name == "operation-lease-heartbeat":
            thread.join(1)

    assert raised.value.code == "lease-heartbeat-shutdown-timeout"
    assert elapsed < 0.5
    assert not any(
        thread.name == "operation-lease-heartbeat"
        for thread in threading.enumerate()
    )


@pytest.mark.parametrize("cancel", [False, True], ids=["lease-loss", "cancel"])
def test_lease_state_discovered_while_stopping_supersedes_processing_error(
    lease, monkeypatch, caplog, cancel
):
    processing_failed = threading.Event()
    heartbeat_entered = threading.Event()
    release_heartbeat = threading.Event()
    real_renew = operations.renew_lease

    def fail_heartbeat_after_processing(current_lease, **kwargs):
        if (
            threading.current_thread().name == "operation-lease-heartbeat"
            and processing_failed.is_set()
        ):
            heartbeat_entered.set()
            assert release_heartbeat.wait(1)
            if cancel:
                operations.request_cancel(
                    lease.operation_id, by="owner@smith.edu"
                )
                return real_renew(current_lease, **kwargs)
            raise operations.OperationError("operation is no longer running")
        return real_renew(current_lease, **kwargs)

    def processing_error(tasks, *, tmp_dir, **kwargs):
        processing_failed.set()
        assert heartbeat_entered.wait(1)
        release_heartbeat.set()
        output = tmp_dir / "output.mrc"
        output.write_bytes(b"")
        return sandbox.SandboxResult(
            output_path=output,
            errors=[],
            timed_out=True,
        )

    monkeypatch.setattr(operation_runner, "_LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        operation_runner.operations,
        "renew_lease",
        fail_heartbeat_after_processing,
    )
    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        processing_error,
    )

    expected = (
        operation_runner.OperationCancelled
        if cancel
        else operations.OperationError
    )
    with pytest.raises(expected):
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert "'code': 'chunk-timeout'" in caplog.text
    assert not (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    ).exists()


def test_unexpected_attempt_log_redacts_exception_message(lease, caplog):
    sensitive_value = "private-task-or-input-value"
    try:
        raise RuntimeError(sensitive_value)
    except RuntimeError as exc:
        with caplog.at_level(
            "ERROR", logger="marcedit_web.operation_runner"
        ):
            operation_runner._log_failed_attempt(lease, exc)

    assert "Traceback" in caplog.text
    assert "private-task-or-input-value" not in caplog.text
    assert str(lease.operation_id) in caplog.text


def test_input_permission_errors_have_a_stable_run_error(lease, monkeypatch):
    input_path = Path(lease.input_artifact["file_path"])
    real_open = Path.open

    def deny_input(path, *args, **kwargs):
        if path == input_path:
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_input)

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert raised.value.code == "input-unreadable"


def test_candidate_permission_errors_have_a_stable_run_error(lease, monkeypatch):
    candidate_path = (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
        / "candidate.mrc"
    )
    real_open = Path.open

    def deny_candidate(path, *args, **kwargs):
        if path == candidate_path:
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_candidate)

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert raised.value.code == "candidate-unwritable"


def test_chunk_output_permission_errors_have_a_stable_run_error(
    lease, monkeypatch
):
    real_open = Path.open

    def deny_output(path, *args, **kwargs):
        if path.name == "output.mrc" and args and args[0] == "rb":
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_output)

    with pytest.raises(operation_runner.OperationRunError) as raised:
        operation_runner.run_saved_task_operation(lease, chunk_size=5)

    assert raised.value.code == "output-unreadable"
