"""Durable operation worker tests for TASK-156."""

from __future__ import annotations

import io
import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import db, job_files, jobs, operation_runner, operations
from marcedit_web.ops import worker


def _mrc_bytes(count: int = 1) -> bytes:
    output = io.BytesIO()
    writer = pymarc.MARCWriter(output)
    for index in range(count):
        record = pymarc.Record()
        record.add_field(pymarc.Field(tag="001", data=str(index + 1)))
        writer.write(record)
    writer.close(close_fh=False)
    return output.getvalue()


def _queue_operation(*, submitted_at: str = "2026-07-16T12:00:00Z") -> int:
    root = operations.operations_root()
    root.mkdir(parents=True, exist_ok=True)
    input_path = root / f"input-{submitted_at[-3:-1]}.mrc"
    if input_path.exists():
        input_path = root / f"input-{len(list(root.glob('input-*.mrc')))}.mrc"
    input_path.write_bytes(_mrc_bytes())
    request = {
        "version": 1,
        "tasks": [{"name": "noop", "body": "pass", "imports": []}],
    }
    db.init_schema()
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO operations(kind, submitted_by, state, request_json,"
            " total_records, submitted_at, artifacts_expire_at)"
            " VALUES ('saved-task-run', 'owner@smith.edu', 'queued', ?, 1, ?, ?)",
            (json.dumps(request), submitted_at, "2026-08-15T12:00:00Z"),
        )
        operation_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO operation_artifacts(operation_id, role, filename,"
            " file_path, record_count, file_bytes, queue_owned, created_at,"
            " expires_at) VALUES (?, 'input', 'input.mrc', ?, 1, ?, 1, ?, ?)",
            (
                operation_id,
                str(input_path),
                input_path.stat().st_size,
                submitted_at,
                "2026-08-15T12:00:00Z",
            ),
        )
    return operation_id


def _outcome(lease: operations.Lease, *, errors: int = 0):
    attempt = (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    )
    attempt.mkdir(parents=True, exist_ok=True)
    candidate = attempt / "candidate.mrc"
    candidate.write_bytes(_mrc_bytes())
    details = tuple(
        {"index": 1, "code": "task-error", "message": "safe"}
        for _ in range(errors)
    )
    return operation_runner.RunOutcome(
        candidate_path=candidate,
        input_records=1,
        output_records=1,
        changed_records=1,
        error_count=errors,
        errors=details,
        summary={"total_in": 1, "total_out": 1, "changed_count": 1},
    )


def test_run_once_claims_only_one_operation_and_completes_it(monkeypatch):
    first = _queue_operation(submitted_at="2026-07-16T12:00:00Z")
    second = _queue_operation(submitted_at="2026-07-16T12:00:01Z")
    monkeypatch.setattr(
        worker.operation_runner,
        "run_saved_task_operation",
        lambda lease: _outcome(lease),
    )

    assert worker.run_once("worker-a") is True

    assert operations.get_operation(first)["state"] == "completed"
    assert operations.get_operation(second)["state"] == "queued"
    assert operations.worker_health()["row"]["current_operation_id"] is None
    assert not (
        operations.operations_root() / str(first) / "attempt-1"
    ).exists()


def test_cancellation_after_runner_return_removes_private_candidate(monkeypatch):
    operation_id = _queue_operation()
    real_complete = operations.complete_operation

    def cancel_before_publication(lease, **kwargs):
        operations.request_cancel(lease.operation_id, by="owner@smith.edu")
        return real_complete(lease, **kwargs)

    monkeypatch.setattr(
        worker.operation_runner,
        "run_saved_task_operation",
        lambda lease: _outcome(lease),
    )
    monkeypatch.setattr(worker.operations, "complete_operation", cancel_before_publication)

    assert worker.run_once("worker-a") is True

    assert operations.get_operation(operation_id)["state"] == "cancelled"
    assert not (
        operations.operations_root() / str(operation_id) / "attempt-1"
    ).exists()


def test_active_operation_refreshes_worker_health_past_stale_limit(monkeypatch):
    _queue_operation()
    entered = threading.Event()
    release = threading.Event()
    failures = []
    monkeypatch.setattr(worker, "_WORKER_HEARTBEAT_SECONDS", 0.01)

    def block(lease):
        entered.set()
        assert release.wait(2)
        return _outcome(lease)

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", block)

    def run():
        try:
            worker.run_once("worker-a")
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(1)
    with db.connect() as conn:
        conn.execute(
            "UPDATE queue_worker_status SET heartbeat_at=? WHERE singleton=1",
            ("2000-01-01T00:00:00Z",),
        )
    deadline = time.monotonic() + 1
    while not operations.worker_health()["available"]:
        assert time.monotonic() < deadline
        time.sleep(0.01)

    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert failures == []
    assert not any(
        current.name == "operation-worker-heartbeat"
        for current in threading.enumerate()
    )


def test_run_once_logs_warning_completion_without_leaking_request(caplog, monkeypatch):
    operation_id = _queue_operation()
    secret = "secret-task-body-value"
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET request_json=? WHERE id=?",
            (
                json.dumps(
                    {
                        "version": 1,
                        "tasks": [{"name": secret, "body": secret}],
                    }
                ),
                operation_id,
            ),
        )
    monkeypatch.setattr(
        worker.operation_runner,
        "run_saved_task_operation",
        lambda lease: _outcome(lease, errors=1),
    )

    with caplog.at_level(logging.INFO, logger="marcedit_web.operation_worker"):
        worker.run_once("worker-a")

    row = operations.get_operation(operation_id)
    assert row["state"] == "completed"
    assert row["error_count"] == 1
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert secret not in caplog.text


def test_expected_runner_failure_uses_safe_message_without_stack_trace(
    caplog, monkeypatch
):
    operation_id = _queue_operation()

    def fail(_lease):
        raise operation_runner.OperationRunError("input-missing", "Input is gone.")

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", fail)
    with caplog.at_level(logging.INFO, logger="marcedit_web.operation_worker"):
        worker.run_once("worker-a")

    row = operations.get_operation(operation_id)
    assert row["state"] == "failed"
    assert row["terminal_message"] == "Input is gone."
    assert "Traceback" not in caplog.text


def test_unexpected_failure_logs_stack_trace_but_persists_generic_message(
    caplog, monkeypatch
):
    operation_id = _queue_operation()
    secret = "sensitive-input-path"

    def crash(_lease):
        raise RuntimeError(secret)

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", crash)
    with caplog.at_level(logging.ERROR, logger="marcedit_web.operation_worker"):
        worker.run_once("worker-a")

    row = operations.get_operation(operation_id)
    assert row["state"] == "failed"
    assert row["terminal_message"] == (
        "Processing failed because of an internal worker error."
    )
    assert "Traceback" in caplog.text
    assert secret not in caplog.text


def test_genuine_runner_cancellation_finishes_cancelled(monkeypatch):
    operation_id = _queue_operation()

    def cancel(lease):
        operations.request_cancel(lease.operation_id, by="owner@smith.edu")
        raise operation_runner.OperationCancelled("cancelled")

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", cancel)

    assert worker.run_once("worker-a") is True
    assert operations.get_operation(operation_id)["state"] == "cancelled"


def test_lost_lease_is_not_failed_or_overwritten(monkeypatch):
    operation_id = _queue_operation()

    def lose_lease(lease):
        with db.connect() as conn:
            conn.execute(
                "UPDATE operations SET state='queued', phase='queued',"
                " lease_owner=NULL, lease_token=NULL, lease_heartbeat_at=NULL,"
                " lease_expires_at=NULL, processed_records=0 WHERE id=?",
                (lease.operation_id,),
            )
        raise operations.OperationError("operation is no longer running")

    monkeypatch.setattr(
        worker.operation_runner, "run_saved_task_operation", lose_lease
    )

    with pytest.raises(operations.OperationError, match="no longer running"):
        worker.run_once("worker-a")

    row = operations.get_operation(operation_id)
    assert row["state"] == "queued"
    assert row["terminal_message"] == ""


def test_cancelled_exception_from_stale_lease_is_not_misclassified(monkeypatch):
    operation_id = _queue_operation()

    def stale_cancel(lease):
        with db.connect() as conn:
            conn.execute(
                "UPDATE operations SET state='queued', phase='queued',"
                " lease_owner=NULL, lease_token=NULL, lease_heartbeat_at=NULL,"
                " lease_expires_at=NULL WHERE id=?",
                (lease.operation_id,),
            )
        raise operation_runner.OperationCancelled("not a user cancellation")

    monkeypatch.setattr(
        worker.operation_runner, "run_saved_task_operation", stale_cancel
    )

    with pytest.raises(operation_runner.OperationCancelled):
        worker.run_once("worker-a")
    assert operations.get_operation(operation_id)["state"] == "queued"


def test_cancel_winning_failure_transition_finishes_cancelled(monkeypatch):
    operation_id = _queue_operation()

    def fail(_lease):
        raise operation_runner.OperationRunError("chunk-timeout", "Too long.")

    real_fail = operations.fail_operation

    def cancel_before_fail(lease, **kwargs):
        operations.request_cancel(lease.operation_id, by="owner@smith.edu")
        return real_fail(lease, **kwargs)

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", fail)
    monkeypatch.setattr(worker.operations, "fail_operation", cancel_before_fail)

    assert worker.run_once("worker-a") is True
    assert operations.get_operation(operation_id)["state"] == "cancelled"


@pytest.mark.parametrize("unexpected", [False, True], ids=["expected", "internal"])
def test_cancellation_between_failure_and_transition_wins(
    monkeypatch, unexpected
):
    operation_id = _queue_operation()
    failure = (
        RuntimeError("internal")
        if unexpected
        else operation_runner.OperationRunError("chunk-timeout", "Too long.")
    )

    def fail(_lease):
        raise failure

    real_fail = operations.fail_operation

    def cancel_at_guard(lease, **kwargs):
        operations.request_cancel(lease.operation_id, by="owner@smith.edu")
        return real_fail(lease, **kwargs)

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", fail)
    monkeypatch.setattr(worker.operations, "fail_operation", cancel_at_guard)

    assert worker.run_once("worker-a") is True
    assert operations.get_operation(operation_id)["state"] == "cancelled"


@pytest.mark.parametrize("unexpected", [False, True], ids=["expected", "internal"])
def test_lease_loss_at_failure_guard_propagates_original_without_overwrite(
    monkeypatch, unexpected
):
    operation_id = _queue_operation()
    failure = (
        RuntimeError("internal")
        if unexpected
        else operation_runner.OperationRunError("chunk-timeout", "Too long.")
    )

    def fail(_lease):
        raise failure

    real_fail = operations.fail_operation

    def lose_at_guard(lease, **kwargs):
        with db.connect() as conn:
            conn.execute(
                "UPDATE operations SET state='queued', phase='queued',"
                " lease_owner=NULL, lease_token=NULL, lease_heartbeat_at=NULL,"
                " lease_expires_at=NULL WHERE id=?",
                (lease.operation_id,),
            )
        return real_fail(lease, **kwargs)

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", fail)
    monkeypatch.setattr(worker.operations, "fail_operation", lose_at_guard)

    with pytest.raises(type(failure)) as raised:
        worker.run_once("worker-a")
    assert raised.value is failure
    row = operations.get_operation(operation_id)
    assert row["state"] == "queued"
    assert row["terminal_message"] == ""


def test_worker_restart_recovers_then_restarts_from_zero(monkeypatch):
    operation_id = _queue_operation()
    old_lease = operations.claim_next("dead-worker")
    assert old_lease is not None
    operations.renew_lease(old_lease, processed_records=1)
    stale_attempt = (
        operations.operations_root()
        / str(operation_id)
        / f"attempt-{old_lease.attempt}"
    )
    stale_attempt.mkdir(parents=True)
    (stale_attempt / "candidate.mrc").write_bytes(b"partial")
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET lease_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00Z", operation_id),
        )
    observed = []

    def run(lease):
        row = operations.get_operation(operation_id)
        observed.append((lease.attempt, row["processed_records"]))
        return _outcome(lease)

    monkeypatch.setattr(worker.operation_runner, "run_saved_task_operation", run)

    worker.run_once("replacement-worker")

    events = operations.list_events(operation_id, "owner@smith.edu")
    assert any(event["kind"] == "recovered" for event in events)
    assert observed == [(2, 0)]
    assert not stale_attempt.exists()


def test_idle_worker_heartbeats_and_check_has_exact_output(capsys):
    assert worker.run_once("idle-worker") is False
    assert worker.main(["--check"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "ok\n"
    assert captured.err == ""


def test_stale_worker_check_has_exact_error(capsys):
    assert worker.main(["--check"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "operation worker heartbeat is stale or missing\n"


def test_run_forever_stops_after_current_control_boundary(monkeypatch):
    handlers = {}
    calls = []
    cleanup_calls = []
    monkeypatch.setattr(
        worker.signal,
        "signal",
        lambda signum, handler: handlers.setdefault(signum, handler),
    )
    monkeypatch.setattr(
        worker.operations,
        "cleanup_expired_artifacts",
        lambda: cleanup_calls.append(True) or 0,
    )

    def one_control_boundary(worker_id):
        calls.append(worker_id)
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return True

    monkeypatch.setattr(worker, "run_once", one_control_boundary)

    assert worker.run_forever("worker-a", poll_seconds=0.01) == 0
    assert calls == ["worker-a"]
    assert cleanup_calls == [True]


def test_run_forever_configures_json_line_info_logging(monkeypatch, caplog):
    handlers = {}
    configured = []
    monkeypatch.setattr(
        worker.signal,
        "signal",
        lambda signum, handler: handlers.setdefault(signum, handler),
    )
    monkeypatch.setattr(worker, "_cleanup_safely", lambda: None)
    monkeypatch.setattr(
        worker.logging,
        "basicConfig",
        lambda **kwargs: configured.append(kwargs),
    )

    def stop_after_start(_worker_id):
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return False

    monkeypatch.setattr(worker, "run_once", stop_after_start)

    with caplog.at_level(logging.INFO, logger="marcedit_web.operation_worker"):
        assert worker.run_forever("worker-a", poll_seconds=0.01) == 0

    assert configured[0]["level"] == logging.INFO
    formatter = configured[0]["handlers"][0].formatter
    record = logging.makeLogRecord(
        {
            "name": "marcedit_web.operation_worker",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "operation worker started",
            "worker_id": "worker a",
        }
    )
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "marcedit_web.operation_worker"
    assert payload["message"] == "operation worker started"
    assert payload["context"] == {"worker_id": "worker a"}
    assert payload["timestamp"].endswith("Z")
    assert "operation worker started" in caplog.text
    assert caplog.records[0].worker_id == "worker-a"


def test_run_forever_restores_previous_signal_handlers(monkeypatch):
    previous = {
        signal.SIGTERM: object(),
        signal.SIGINT: object(),
    }
    installed = []
    current = dict(previous)

    def install(signum, handler):
        installed.append((signum, handler))
        old = current[signum]
        current[signum] = handler
        return old

    monkeypatch.setattr(worker.signal, "getsignal", current.__getitem__)
    monkeypatch.setattr(worker.signal, "signal", install)
    monkeypatch.setattr(worker.operations, "cleanup_expired_artifacts", lambda: 0)

    def stop_during_poll(_worker_id):
        current[signal.SIGINT](signal.SIGINT, None)
        return False

    monkeypatch.setattr(worker, "run_once", stop_during_poll)

    assert worker.run_forever("worker-a", poll_seconds=0.01) == 0
    assert current == previous
    assert [signum for signum, _handler in installed] == [
        signal.SIGTERM,
        signal.SIGINT,
        signal.SIGINT,
        signal.SIGTERM,
    ]


def test_run_forever_restores_sigterm_when_sigint_install_fails(monkeypatch):
    previous_term = object()
    previous_int = object()
    current_term = previous_term

    monkeypatch.setattr(
        worker.signal,
        "getsignal",
        lambda signum: (
            previous_term if signum == signal.SIGTERM else previous_int
        ),
    )

    def install(signum, handler):
        nonlocal current_term
        if signum == signal.SIGINT and handler not in {
            previous_term,
            previous_int,
        }:
            raise RuntimeError("cannot install SIGINT")
        if signum == signal.SIGTERM:
            current_term = handler

    monkeypatch.setattr(worker.signal, "signal", install)

    with pytest.raises(RuntimeError, match="cannot install SIGINT"):
        worker.run_forever("worker-a")
    assert current_term is previous_term


def _add_expiring_artifact(
    *,
    path: Path,
    expires_at: str,
    queue_owned: int = 1,
    applied: bool = False,
) -> tuple[int, int]:
    operation_id = _queue_operation()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"artifact")
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO operation_artifacts(operation_id, role, filename,"
            " file_path, record_count, file_bytes, queue_owned, created_at,"
            " expires_at) VALUES (?, 'result', 'result.mrc', ?, 1, 8, ?, ?, ?)",
            (
                operation_id,
                str(path),
                queue_owned,
                "2026-06-01T00:00:00Z",
                expires_at,
            ),
        )
        artifact_id = int(cursor.lastrowid)
        if applied:
            conn.execute(
                "UPDATE operations SET applied_at='2026-06-02T00:00:00Z'"
                " WHERE id=?",
                (operation_id,),
            )
    return operation_id, artifact_id


def test_cleanup_deletes_only_expired_queue_owned_unapplied_bytes(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files")
    )
    root = operations.operations_root()
    expired_path = root / "expired" / "result.mrc"
    retained_path = root / "retained" / "result.mrc"
    external_path = tmp_path / "job-version.mrc"
    source = tmp_path / "applied-source.mrc"
    source.write_bytes(b"applied")
    job = jobs.create_job("owner@smith.edu", "Cleanup safety")
    attached = job_files.attach_file(
        job_id=job["id"],
        user_email="owner@smith.edu",
        source_path=source,
        filename="applied.mrc",
        record_count=1,
        file_bytes=7,
    )
    applied_path = Path(
        job_files.get_current_version(
            attached["id"], "owner@smith.edu"
        )["file_path"]
    )
    operation_id, artifact_id = _add_expiring_artifact(
        path=expired_path, expires_at="2026-06-15T00:00:00Z"
    )
    _add_expiring_artifact(
        path=retained_path, expires_at="2026-08-01T00:00:00Z"
    )
    _add_expiring_artifact(
        path=external_path,
        expires_at="2026-06-15T00:00:00Z",
        queue_owned=0,
    )
    _add_expiring_artifact(
        path=applied_path,
        expires_at="2026-06-15T00:00:00Z",
    )

    deleted = operations.cleanup_expired_artifacts(
        datetime(2026, 7, 16, tzinfo=timezone.utc)
    )

    assert deleted == 1
    assert not expired_path.exists()
    assert retained_path.exists() and external_path.exists() and applied_path.exists()
    with db.connect() as conn:
        artifact = conn.execute(
            "SELECT * FROM operation_artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
        event = conn.execute(
            "SELECT * FROM operation_events WHERE operation_id=?"
            " AND kind='artifacts-expired'",
            (operation_id,),
        ).fetchone()
    assert artifact is not None
    assert artifact["file_path"] == str(expired_path)
    assert event is not None
    assert json.loads(event["details_json"])["artifact_id"] == artifact_id


def test_cleanup_failure_logs_ids_and_retries_later(tmp_path, monkeypatch, caplog):
    path = operations.operations_root() / "expired" / "result.mrc"
    operation_id, artifact_id = _add_expiring_artifact(
        path=path, expires_at="2026-06-15T00:00:00Z"
    )
    real_unlink = os.unlink
    attempts = 0
    sensitive_failure = "disk busy"

    def flaky_unlink(target, *args, **kwargs):
        nonlocal attempts
        if target == path.name and attempts == 0:
            attempts += 1
            raise OSError(sensitive_failure)
        return real_unlink(target, *args, **kwargs)

    monkeypatch.setattr(operations.os, "unlink", flaky_unlink)
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    with caplog.at_level(logging.ERROR, logger="marcedit_web.operations"):
        assert operations.cleanup_expired_artifacts(now) == 0
    assert path.exists()
    assert str(operation_id) in caplog.text
    assert str(artifact_id) in caplog.text
    assert "disk busy" not in caplog.text

    assert operations.cleanup_expired_artifacts(now) == 1
    assert not path.exists()


def test_cleanup_missing_bytes_converges_after_post_unlink_db_failure(
    monkeypatch,
):
    path = operations.operations_root() / "expired" / "result.mrc"
    operation_id, artifact_id = _add_expiring_artifact(
        path=path, expires_at="2026-06-15T00:00:00Z"
    )
    real_append = operations._append_event
    fail_once = True

    def fail_after_unlink(conn, target_operation_id, **kwargs):
        nonlocal fail_once
        if kwargs["kind"] == "artifacts-expired" and fail_once:
            fail_once = False
            raise RuntimeError("database commit path failed")
        return real_append(conn, target_operation_id, **kwargs)

    monkeypatch.setattr(operations, "_append_event", fail_after_unlink)
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)

    assert operations.cleanup_expired_artifacts(now) == 0
    assert not path.exists()
    assert operations.cleanup_expired_artifacts(now) == 1
    assert operations.cleanup_expired_artifacts(now) == 0
    with db.connect() as conn:
        events = conn.execute(
            "SELECT details_json FROM operation_events"
            " WHERE operation_id=? AND kind='artifacts-expired'",
            (operation_id,),
        ).fetchall()
        artifact = conn.execute(
            "SELECT id FROM operation_artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
    assert len(events) == 1
    assert json.loads(events[0]["details_json"])["artifact_id"] == artifact_id
    assert artifact is not None


def test_cleanup_refuses_parent_symlink_escape(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("directory no-follow is unavailable")
    root = operations.operations_root()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "result.mrc"
    victim.write_bytes(b"do not delete")
    escaped_parent = root / "escaped"
    escaped_parent.parent.mkdir(parents=True, exist_ok=True)
    escaped_parent.symlink_to(outside, target_is_directory=True)
    _add_expiring_artifact(
        path=escaped_parent / "result.mrc",
        expires_at="2026-06-15T00:00:00Z",
    )

    assert operations.cleanup_expired_artifacts(
        datetime(2026, 7, 16, tzinfo=timezone.utc)
    ) == 0
    assert victim.read_bytes() == b"artifact"


def test_cleanup_parent_swap_cannot_redirect_directory_relative_unlink(
    tmp_path, monkeypatch
):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("directory no-follow is unavailable")
    root = operations.operations_root()
    artifact = root / "swap" / "result.mrc"
    _add_expiring_artifact(
        path=artifact,
        expires_at="2026-06-15T00:00:00Z",
    )
    outside = tmp_path / "outside-swap"
    outside.mkdir()
    victim = outside / "result.mrc"
    victim.write_bytes(b"outside victim")
    moved_parent = root / "swap-original"
    real_relative = operations._relative_queue_path
    swapped = False

    def swap_after_boundary_check(path, operations_root):
        nonlocal swapped
        relative = real_relative(path, operations_root)
        if not swapped:
            swapped = True
            artifact.parent.rename(moved_parent)
            artifact.parent.symlink_to(outside, target_is_directory=True)
        return relative

    monkeypatch.setattr(
        operations, "_relative_queue_path", swap_after_boundary_check
    )

    assert operations.cleanup_expired_artifacts(
        datetime(2026, 7, 16, tzinfo=timezone.utc)
    ) == 0
    assert victim.read_bytes() == b"outside victim"
    assert (moved_parent / "result.mrc").read_bytes() == b"artifact"


def test_top_level_cleanup_log_redacts_exception_value(caplog, monkeypatch):
    sensitive_value = "/private/queue/input-secret.mrc"

    def fail_cleanup():
        raise RuntimeError(sensitive_value)

    monkeypatch.setattr(
        worker.operations, "cleanup_expired_artifacts", fail_cleanup
    )
    with caplog.at_level(logging.ERROR, logger="marcedit_web.operation_worker"):
        worker._cleanup_safely()

    assert "Traceback" in caplog.text
    assert sensitive_value not in caplog.text


def test_cleanup_removes_empty_attempt_parent_directory(tmp_path):
    path = operations.operations_root() / "operation" / "attempt-1" / "result.mrc"
    _add_expiring_artifact(path=path, expires_at="2026-06-15T00:00:00Z")

    operations.cleanup_expired_artifacts(
        datetime(2026, 7, 16, tzinfo=timezone.utc)
    )

    assert not path.parent.exists()
