"""End-to-end durability coverage for the TASK-156 operation queue."""

from __future__ import annotations

import io
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pymarc
import pytest

from marcedit_web.lib import (
    collaboration,
    db,
    job_files,
    jobs,
    operation_results,
    operation_runner,
    operation_submission,
    operations,
    sandbox,
)
from marcedit_web.lib.record_store import RecordStore
from marcedit_web.ops import worker


OWNER = "owner@smith.edu"


def _mrc_bytes(count: int) -> bytes:
    output = io.BytesIO()
    writer = pymarc.MARCWriter(output)
    for index in range(count):
        record = pymarc.Record()
        record.add_field(pymarc.Field(tag="001", data=str(index + 1)))
        writer.write(record)
    writer.close(close_fh=False)
    return output.getvalue()


def _task(body: str = "record['001'].data += 'x'") -> sandbox.TaskSpec:
    return sandbox.TaskSpec(name="integration task", body=body)


def _submit_quick(
    tmp_path: Path,
    *,
    count: int = 12,
    task: Optional[sandbox.TaskSpec] = None,
) -> dict:
    source = tmp_path / f"source-{time.monotonic_ns()}.mrc"
    source.write_bytes(_mrc_bytes(count))
    return operation_submission.submit_quick_load_task_run(
        user_email=OWNER,
        source_path=source,
        filename="vendor.mrc",
        record_count=count,
        task_specs=[task or _task()],
    )


def _expire_lease(operation_id: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET lease_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00Z", operation_id),
        )


def _result_artifacts(operation_id: int) -> list[dict]:
    return [
        artifact
        for artifact in operations.list_artifacts(operation_id, OWNER)
        if artifact["role"] == "result"
    ]


def test_browser_loss_and_app_reinitialization_do_not_interrupt_work(tmp_path):
    submitted = _submit_quick(tmp_path)
    operation_id = submitted["id"]

    del submitted
    db.reset_for_tests()

    assert worker.run_once("replacement-app-worker") is True
    completed = operations.get_operation(operation_id)
    results = _result_artifacts(operation_id)
    assert completed["state"] == "completed"
    assert completed["processed_records"] == 12
    assert len(results) == 1
    assert RecordStore.from_path(Path(results[0]["file_path"])).count() == 12


def test_worker_restart_discards_first_attempt_and_publishes_once(
    tmp_path, monkeypatch
):
    submitted = _submit_quick(tmp_path)
    operation_id = submitted["id"]
    real_sandbox = operation_runner.sandbox.run_tasks_subprocess
    completed_chunks = 0

    class SimulatedProcessLoss(BaseException):
        pass

    def lose_process_after_first_chunk(*args, **kwargs):
        nonlocal completed_chunks
        result = real_sandbox(*args, **kwargs)
        completed_chunks += 1
        raise SimulatedProcessLoss()

    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        lose_process_after_first_chunk,
    )
    with pytest.raises(SimulatedProcessLoss):
        worker.run_once("interrupted-worker")

    assert completed_chunks == 1
    assert operations.get_operation(operation_id)["state"] == "running"
    assert _result_artifacts(operation_id) == []
    assert not (
        operations.operations_root() / str(operation_id) / "attempt-1"
    ).exists()

    monkeypatch.setattr(
        operation_runner.sandbox,
        "run_tasks_subprocess",
        real_sandbox,
    )
    _expire_lease(operation_id)
    assert operations.recover_expired() == 1
    assert worker.run_once("replacement-worker") is True

    completed = operations.get_operation(operation_id)
    results = _result_artifacts(operation_id)
    assert completed["state"] == "completed"
    assert completed["attempt"] == 2
    assert len(results) == 1
    assert RecordStore.from_path(Path(results[0]["file_path"])).count() == 12


def test_stale_worker_cannot_publish_after_recovery(tmp_path):
    submitted = _submit_quick(tmp_path, count=2)
    operation_id = submitted["id"]
    stale = operations.claim_next("stale-worker")
    assert stale is not None
    attempt = (
        operations.operations_root()
        / str(operation_id)
        / f"attempt-{stale.attempt}"
    )
    attempt.mkdir(parents=True)
    candidate = attempt / "candidate.mrc"
    candidate.write_bytes(_mrc_bytes(2))

    _expire_lease(operation_id)
    assert operations.recover_expired() == 1
    current = operations.claim_next("current-worker")
    assert current is not None

    with pytest.raises(operations.OperationError, match="no longer running"):
        operations.complete_operation(
            stale,
            result_path=candidate,
            output_records=2,
            changed_records=0,
            error_count=0,
            errors=[],
            summary={},
        )

    assert _result_artifacts(operation_id) == []
    assert operations.get_operation(operation_id)["lease_token"] == current.token


def test_competing_workers_claim_one_attempt(tmp_path):
    operation_id = _submit_quick(tmp_path, count=2)["id"]
    barrier = threading.Barrier(2)
    claims: list[Optional[operations.Lease]] = []

    def claim(worker_id: str) -> None:
        barrier.wait(timeout=2)
        claims.append(operations.claim_next(worker_id))

    threads = [
        threading.Thread(target=claim, args=(worker_id,))
        for worker_id in ("worker-a", "worker-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(claim is not None for claim in claims) == 1
    assert operations.get_operation(operation_id)["attempt"] == 1


def test_running_cancellation_stops_real_sandbox_without_partial_result(
    tmp_path, monkeypatch
):
    operation_id = _submit_quick(
        tmp_path,
        count=2,
        task=_task("while True:\n    pass"),
    )["id"]
    monkeypatch.setattr(operation_runner.sandbox, "_TERMINATION_GRACE_SECONDS", 0.1)
    failures: list[BaseException] = []

    def run() -> None:
        try:
            worker.run_once("cancellable-worker")
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 10
    while operations.get_operation(operation_id)["state"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.01)

    operations.request_cancel(operation_id, by=OWNER)
    thread.join(10)

    assert not thread.is_alive()
    assert failures == []
    assert operations.get_operation(operation_id)["state"] == "cancelled"
    assert _result_artifacts(operation_id) == []
    assert not (
        operations.operations_root() / str(operation_id) / "attempt-1"
    ).exists()


def test_record_errors_complete_with_exact_count_and_cardinality(tmp_path):
    operation_id = _submit_quick(
        tmp_path,
        count=4,
        task=_task("raise RuntimeError('expected record error')"),
    )["id"]

    assert worker.run_once("warning-worker") is True

    completed = operations.get_operation(operation_id)
    results = _result_artifacts(operation_id)
    assert completed["state"] == "completed"
    assert completed["error_count"] == 4
    assert len(operations.list_errors(operation_id, OWNER)) == 4
    assert len(results) == 1
    assert RecordStore.from_path(Path(results[0]["file_path"])).count() == 4


def test_job_result_can_be_applied_then_rolled_back(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files")
    )
    source = tmp_path / "job-source.mrc"
    source.write_bytes(_mrc_bytes(2))
    job = jobs.create_job(OWNER, "Integration queue")
    attached = job_files.attach_file(
        job_id=job["id"],
        user_email=OWNER,
        source_path=source,
        filename="vendor.mrc",
        record_count=2,
        file_bytes=source.stat().st_size,
    )
    source_version = job_files.get_current_version(attached["id"], OWNER)
    operation_id = operation_submission.submit_job_task_run(
        user_email=OWNER,
        file_id=attached["id"],
        source_version_id=source_version["id"],
        task_specs=[_task()],
    )["id"]

    assert worker.run_once("job-worker") is True
    assert collaboration.acquire_file_checkout(attached["id"], OWNER).acquired
    applied = operation_results.apply_job_result(
        operation_id,
        user_email=OWNER,
        opened_version_id=source_version["id"],
    )
    rolled_back = operation_results.rollback_job_result(
        operation_id,
        user_email=OWNER,
        opened_version_id=applied["id"],
    )

    operation = operations.get_operation(operation_id)
    assert operation["applied_version_id"] == applied["id"]
    assert operation["rolled_back_version_id"] == rolled_back["id"]
    assert Path(rolled_back["file_path"]).read_bytes() == Path(
        source_version["file_path"]
    ).read_bytes()


def test_quick_load_result_reopens_after_worker_completion(
    tmp_path, monkeypatch
):
    operation_id = _submit_quick(tmp_path, count=2)["id"]
    assert worker.run_once("quick-load-worker") is True
    state = {"user": OWNER, "store": None}
    fake_streamlit = SimpleNamespace(session_state=state, query_params={})
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    store = operation_results.reopen_quick_load(
        operation_id,
        user_email=OWNER,
        use_result=True,
    )

    assert store.count() == 2
    assert store.filename == "vendor-queued-result.mrc"
    assert state["store"] is store
    assert len(_result_artifacts(operation_id)) == 1
