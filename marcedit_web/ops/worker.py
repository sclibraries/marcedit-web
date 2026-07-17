"""Durable worker process for queued MARC operations."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
import uuid

from marcedit_web.lib import operation_runner, operations


logger = logging.getLogger("marcedit_web.operation_worker")

_CLEANUP_INTERVAL_SECONDS = 60 * 60
_WORKER_HEARTBEAT_SECONDS = 5.0
_WORKER_HEARTBEAT_STOP_SECONDS = 6.0


class _ActiveWorkerHeartbeat:
    """Keep worker health fresh independently of the operation lease."""

    def __init__(self, worker_id: str, operation_id: int) -> None:
        self._worker_id = worker_id
        self._operation_id = operation_id
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="operation-worker-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop_and_check(self) -> None:
        self._stop.set()
        self._thread.join(_WORKER_HEARTBEAT_STOP_SECONDS)
        if self._thread.is_alive():
            raise RuntimeError(
                "operation worker heartbeat did not stop within the safety limit"
            )
        with self._lock:
            failure = self._failure
        if failure is not None:
            raise failure

    def _run(self) -> None:
        while not self._stop.wait(_WORKER_HEARTBEAT_SECONDS):
            try:
                operations.heartbeat_worker(
                    self._worker_id,
                    current_operation_id=self._operation_id,
                )
            except BaseException as exc:
                with self._lock:
                    self._failure = exc
                return


def run_once(worker_id: str) -> bool:
    """Recover stale work and claim at most one queued operation."""
    operations.heartbeat_worker(worker_id, current_operation_id=None)
    recovered = operations.recover_expired()
    if recovered:
        logger.info("recovered expired operation leases count=%s", recovered)
    lease = operations.claim_next(worker_id)
    if lease is None:
        return False
    operations.heartbeat_worker(
        worker_id,
        current_operation_id=lease.operation_id,
    )
    active_heartbeat = _ActiveWorkerHeartbeat(worker_id, lease.operation_id)
    active_heartbeat.start()
    logger.info(
        "queued operation started operation_id=%s attempt=%s worker_id=%s",
        lease.operation_id,
        lease.attempt,
        worker_id,
    )
    try:
        outcome = operation_runner.run_saved_task_operation(lease)
        operations.complete_operation(
            lease,
            result_path=outcome.candidate_path,
            output_records=outcome.output_records,
            changed_records=outcome.changed_records,
            error_count=outcome.error_count,
            errors=list(outcome.errors),
            summary=outcome.summary,
        )
        log = logger.warning if outcome.error_count else logger.info
        log(
            "queued operation completed operation_id=%s attempt=%s"
            " output_records=%s changed_records=%s error_count=%s",
            lease.operation_id,
            lease.attempt,
            outcome.output_records,
            outcome.changed_records,
            outcome.error_count,
        )
    except operation_runner.OperationCancelled as exc:
        try:
            operations.finish_cancelled(lease)
        except operations.OperationError:
            raise exc
        logger.info(
            "queued operation cancelled operation_id=%s attempt=%s",
            lease.operation_id,
            lease.attempt,
        )
    except operation_runner.OperationRunError as exc:
        if _fail_or_finish_cancelled(
            lease,
            code=exc.code,
            message=str(exc),
            failure=exc,
        ):
            logger.warning(
                "queued operation failed operation_id=%s attempt=%s code=%s",
                lease.operation_id,
                lease.attempt,
                exc.code,
            )
    except Exception as exc:
        _log_internal_failure(lease, exc)
        _fail_or_finish_cancelled(
            lease,
            code="worker-internal-error",
            message="Processing failed because of an internal worker error.",
            failure=exc,
        )
    finally:
        try:
            active_heartbeat.stop_and_check()
        finally:
            operations.heartbeat_worker(worker_id, current_operation_id=None)
    return True


def run_forever(
    worker_id: str | None = None,
    poll_seconds: float = 1.0,
) -> int:
    """Poll until SIGTERM or SIGINT reaches a worker control boundary."""
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    identity = worker_id or f"{os.getpid()}-{uuid.uuid4().hex}"
    stopping = threading.Event()

    def stop(_signum, _frame) -> None:
        stopping.set()

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    previous_sigint = signal.getsignal(signal.SIGINT)
    sigterm_installed = False
    sigint_installed = False
    try:
        signal.signal(signal.SIGTERM, stop)
        sigterm_installed = True
        signal.signal(signal.SIGINT, stop)
        sigint_installed = True
        _cleanup_safely()
        last_cleanup = time.monotonic()
        while not stopping.is_set():
            worked = run_once(identity)
            if stopping.is_set():
                break
            if worked:
                continue
            now = time.monotonic()
            if now - last_cleanup >= _CLEANUP_INTERVAL_SECONDS:
                _cleanup_safely()
                last_cleanup = now
            stopping.wait(poll_seconds)
        return 0
    finally:
        if sigint_installed:
            signal.signal(signal.SIGINT, previous_sigint)
        if sigterm_installed:
            signal.signal(signal.SIGTERM, previous_sigterm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the marcedit-web durable operation worker.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check whether the worker heartbeat is fresh",
    )
    args = parser.parse_args(argv)
    if args.check:
        if operations.worker_health(max_age_seconds=15)["available"]:
            print("ok")
            return 0
        print(
            "operation worker heartbeat is stale or missing",
            file=sys.stderr,
        )
        return 1
    return run_forever()


def _log_internal_failure(
    lease: operations.Lease,
    exc: BaseException,
) -> None:
    safe_exception = RuntimeError("internal worker error")
    logger.error(
        "queued operation failed operation_id=%s attempt=%s",
        lease.operation_id,
        lease.attempt,
        exc_info=(RuntimeError, safe_exception, exc.__traceback__),
    )


def _fail_or_finish_cancelled(
    lease: operations.Lease,
    *,
    code: str,
    message: str,
    failure: BaseException,
) -> bool:
    """Fail the current lease unless a concurrent cancellation won."""
    try:
        operations.fail_operation(lease, code=code, message=message)
        return True
    except operations.OperationError as transition_error:
        if not operations.is_lease_cancelling(lease):
            raise failure from transition_error
        operations.finish_cancelled(lease)
        return False


def _cleanup_safely() -> None:
    try:
        deleted = operations.cleanup_expired_artifacts()
    except Exception as exc:
        logger.error(
            "operation artifact cleanup pass failed",
            exc_info=(
                RuntimeError,
                RuntimeError("operation artifact cleanup error"),
                exc.__traceback__,
            ),
        )
        return
    if deleted:
        logger.info("expired operation artifacts removed count=%s", deleted)


if __name__ == "__main__":
    raise SystemExit(main())
