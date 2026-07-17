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
    except operation_runner.OperationCancelled:
        if not operations.is_lease_cancelling(lease):
            raise
        operations.finish_cancelled(lease)
        logger.info(
            "queued operation cancelled operation_id=%s attempt=%s",
            lease.operation_id,
            lease.attempt,
        )
    except operation_runner.OperationRunError as exc:
        if operations.is_lease_cancelling(lease):
            operations.finish_cancelled(lease)
        elif _lease_is_current(lease):
            if _fail_or_finish_cancelled(
                lease,
                code=exc.code,
                message=str(exc),
            ):
                logger.warning(
                    "queued operation failed operation_id=%s attempt=%s code=%s",
                    lease.operation_id,
                    lease.attempt,
                    exc.code,
                )
        else:
            raise operations.OperationError(
                "operation lease is no longer current"
            ) from exc
    except Exception as exc:
        if operations.is_lease_cancelling(lease):
            operations.finish_cancelled(lease)
        elif not _lease_is_current(lease):
            raise
        else:
            _log_internal_failure(lease, exc)
            _fail_or_finish_cancelled(
                lease,
                code="worker-internal-error",
                message="Processing failed because of an internal worker error.",
            )
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

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
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


def _lease_is_current(lease: operations.Lease) -> bool:
    current = operations.get_operation(lease.operation_id)
    return (
        current["state"] == "running"
        and current["lease_token"] == lease.token
    )


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
) -> bool:
    """Fail the current lease unless a concurrent cancellation won."""
    try:
        operations.fail_operation(lease, code=code, message=message)
        return True
    except operations.OperationError:
        if not operations.is_lease_cancelling(lease):
            raise
        operations.finish_cancelled(lease)
        return False


def _cleanup_safely() -> None:
    try:
        deleted = operations.cleanup_expired_artifacts()
    except Exception:
        logger.exception("operation artifact cleanup pass failed")
        return
    if deleted:
        logger.info("expired operation artifacts removed count=%s", deleted)


if __name__ == "__main__":
    raise SystemExit(main())
