"""Deterministic, bounded runner for queued saved-task operations."""

from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pymarc

from . import operations, sandbox, task_diff
from .record_store import RecordStore

logger = logging.getLogger("marcedit_web.operation_runner")

_LEASE_HEARTBEAT_SECONDS = 10.0
# ``db.connect`` uses sqlite3's five-second busy timeout.  Six seconds gives
# an in-flight renewal time to finish while keeping attempt shutdown bounded.
_LEASE_HEARTBEAT_STOP_SECONDS = 6.0


class OperationCancelled(RuntimeError):
    """Raised after a requested cancellation stops the sandbox child."""


class OperationRunError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RunOutcome:
    candidate_path: Path
    input_records: int
    output_records: int
    changed_records: int
    error_count: int
    errors: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


class _LeaseHeartbeat:
    """Renew one lease from a dedicated thread during blocking local work."""

    def __init__(self, lease: operations.Lease) -> None:
        self._lease = lease
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._failure: BaseException | None = None
        self._cancelled = False
        self._started = False
        self._thread = threading.Thread(
            target=self._run,
            name="operation-lease-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def stop_and_check(self, *, final_renew: bool = False) -> None:
        """Stop within the SQLite timeout bound and surface renewal state."""
        if not self._started:
            return
        self._stop.set()
        self._thread.join(_LEASE_HEARTBEAT_STOP_SECONDS)
        if self._thread.is_alive():
            raise OperationRunError(
                "lease-heartbeat-shutdown-timeout",
                "Lease maintenance did not stop within the safety limit.",
            )
        self.check()
        if final_renew:
            try:
                operations.renew_lease(self._lease)
            except operations.OperationError as exc:
                if operations.is_lease_cancelling(self._lease):
                    raise OperationCancelled(
                        "Operation cancellation was requested."
                    )
                raise

    def check(self) -> None:
        with self._lock:
            failure = self._failure
            cancelled = self._cancelled
        if cancelled:
            raise OperationCancelled("Operation cancellation was requested.")
        if failure is not None:
            raise failure

    def is_alive(self) -> bool:
        return self._started and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.wait(_LEASE_HEARTBEAT_SECONDS):
            try:
                operations.renew_lease(self._lease)
            except operations.OperationError as exc:
                try:
                    cancelling = operations.is_lease_cancelling(self._lease)
                except BaseException as check_exc:
                    with self._lock:
                        self._failure = check_exc
                    return
                with self._lock:
                    if cancelling:
                        self._cancelled = True
                    else:
                        self._failure = exc
                return
            except BaseException as exc:
                with self._lock:
                    self._failure = exc
                return


def queue_chunk_records() -> int:
    raw = os.environ.get("MARCEDIT_WEB_QUEUE_CHUNK_RECORDS", "5000")
    try:
        size = int(raw)
    except ValueError as exc:
        raise operations.OperationError(
            "MARCEDIT_WEB_QUEUE_CHUNK_RECORDS must be a positive integer"
        ) from exc
    if size <= 0:
        raise operations.OperationError(
            "MARCEDIT_WEB_QUEUE_CHUNK_RECORDS must be a positive integer"
        )
    return size


def run_saved_task_operation(
    lease: operations.Lease,
    *,
    chunk_size: int | None = None,
) -> RunOutcome:
    """Run an immutable saved-task request into a private candidate file."""
    size = queue_chunk_records() if chunk_size is None else chunk_size
    if size <= 0:
        raise operations.OperationError("chunk_size must be positive")
    tasks = _parse_tasks(lease.request)
    input_path = Path(str(lease.input_artifact.get("file_path", "")))
    if not input_path.is_file():
        raise OperationRunError(
            "input-missing", "Operation input file was not found."
        )
    expected_input_records = lease.input_artifact.get("record_count")
    if (
        not isinstance(expected_input_records, int)
        or isinstance(expected_input_records, bool)
        or expected_input_records < 0
    ):
        raise OperationRunError(
            "invalid-request", "Operation input record count is invalid."
        )

    attempt_dir = (
        operations.operations_root()
        / str(lease.operation_id)
        / f"attempt-{lease.attempt}"
    )
    candidate_path = attempt_dir / "candidate.mrc"
    completed = 0
    error_count = 0
    retained_errors: list[dict[str, Any]] = []
    last_progress = -1
    heartbeat = _LeaseHeartbeat(lease)
    cleanup_owned = False

    def renew(*, phase: str | None = None, processed: int | None = None) -> None:
        nonlocal last_progress
        heartbeat.check()
        if processed is not None and processed < last_progress:
            return
        try:
            operations.renew_lease(
                lease,
                phase=phase,
                processed_records=processed,
            )
        except operations.OperationError:
            if operations.is_lease_cancelling(lease):
                raise OperationCancelled("Operation cancellation was requested.")
            raise
        if processed is not None:
            last_progress = processed

    def cancellation_requested() -> bool:
        heartbeat.check()
        if operations.is_lease_cancelling(lease):
            return True
        try:
            operations.renew_lease(lease)
        except operations.OperationError:
            if operations.is_lease_cancelling(lease):
                return True
            raise
        return False

    try:
        heartbeat.start()
        renew()
        cleanup_owned = True
        try:
            if attempt_dir.exists():
                shutil.rmtree(attempt_dir)
            attempt_dir.mkdir(parents=True)
        except OSError as exc:
            raise OperationRunError(
                "candidate-unwritable",
                "Operation workspace could not be prepared.",
            ) from exc
        try:
            input_file = input_path.open("rb")
        except OSError as exc:
            raise OperationRunError(
                "input-unreadable", "Operation input file could not be read."
            ) from exc
        try:
            candidate = candidate_path.open("wb")
        except OSError as exc:
            input_file.close()
            raise OperationRunError(
                "candidate-unwritable", "Operation candidate could not be written."
            ) from exc
        with input_file, candidate:
            reader = iter(
                pymarc.MARCReader(input_file, to_unicode=True, permissive=True)
            )
            chunk_number = 0
            while True:
                chunk_number += 1
                chunk_dir = attempt_dir / f"chunk-{chunk_number}"
                try:
                    chunk_dir.mkdir()
                except OSError as exc:
                    raise OperationRunError(
                        "candidate-unwritable",
                        "Operation chunk workspace could not be prepared.",
                    ) from exc
                chunk_input = chunk_dir / "input.mrc"
                try:
                    chunk_records = _write_chunk(reader, chunk_input, size)
                    if chunk_records == 0:
                        shutil.rmtree(chunk_dir)
                        break
                    renew(phase="processing")
                    completed_before = completed
                    result = sandbox.run_tasks_subprocess(
                        tasks,
                        input_path=chunk_input,
                        timeout=300,
                        tmp_dir=chunk_dir,
                        progress_path=chunk_dir / "progress.json",
                        progress_callback=lambda current: renew(
                            processed=completed_before + current
                        ),
                        cancel_requested=cancellation_requested,
                        poll_interval=1.0,
                    )
                    if result.cancelled:
                        raise OperationCancelled(
                            "Operation cancellation was requested."
                        )
                    if result.timed_out:
                        raise OperationRunError(
                            "chunk-timeout",
                            f"Chunk {chunk_number} reached the maximum processing time.",
                        )
                    if result.returncode != 0:
                        raise OperationRunError(
                            "sandbox-exit",
                            f"Chunk {chunk_number} stopped unexpectedly.",
                        )
                    _validate_chunk_output(
                        result.output_path,
                        expected_records=chunk_records,
                        chunk_number=chunk_number,
                    )
                    error_count += result.error_count
                    for error in result.errors:
                        if len(retained_errors) >= sandbox.MAX_RETAINED_ERRORS:
                            break
                        translated = dict(error)
                        translated["index"] = completed_before + int(
                            translated.get("index", 0)
                        )
                        retained_errors.append(translated)
                    _append_chunk_output(result.output_path, candidate)
                    completed += chunk_records
                    renew(processed=completed)
                finally:
                    shutil.rmtree(chunk_dir, ignore_errors=True)

        if completed != expected_input_records:
            raise OperationRunError(
                "input-cardinality-mismatch",
                "Operation input no longer matches its submitted record count.",
            )
        renew(phase="validating", processed=completed)
        try:
            output_store = RecordStore.from_path(candidate_path)
            output_count = output_store.count()
            iterated_count = sum(1 for _ in output_store.iter_records())
        except OSError as exc:
            raise OperationRunError(
                "candidate-unreadable",
                "Combined output could not be read for validation.",
            ) from exc
        if output_store.malformed_count() or output_count != completed:
            raise OperationRunError(
                "aggregate-invalid",
                "Combined output did not contain the expected records.",
            )
        if iterated_count != completed:
            raise OperationRunError(
                "aggregate-invalid",
                "Combined output contained an unreadable MARC record.",
            )
        try:
            diff = task_diff.compute_task_diff(input_path, candidate_path)
        except OSError as exc:
            raise OperationRunError(
                "validation-io-error",
                "Input or combined output could not be read for validation.",
            ) from exc
        if diff.total_in != completed or diff.total_out != completed:
            raise OperationRunError(
                "aggregate-invalid",
                "Combined output failed final record validation.",
            )
        renew(processed=completed)
        outcome = RunOutcome(
            candidate_path=candidate_path,
            input_records=completed,
            output_records=output_count,
            changed_records=diff.changed_count,
            error_count=error_count,
            errors=tuple(retained_errors),
            summary=asdict(diff),
        )
        heartbeat.stop_and_check(final_renew=True)
        return outcome
    except BaseException as exc:
        shutdown_timed_out = (
            isinstance(exc, OperationRunError)
            and exc.code == "lease-heartbeat-shutdown-timeout"
        )
        if heartbeat.is_alive() and not shutdown_timed_out:
            try:
                heartbeat.stop_and_check()
            except BaseException:
                logger.exception(
                    "lease heartbeat shutdown failed"
                    " operation_id=%s attempt=%s",
                    lease.operation_id,
                    lease.attempt,
                )
        _log_failed_attempt(lease, exc)
        if cleanup_owned:
            shutil.rmtree(attempt_dir, ignore_errors=True)
        raise


def _parse_tasks(request: dict[str, Any]) -> tuple[sandbox.TaskSpec, ...]:
    if request.get("version") != 1 or isinstance(request.get("version"), bool):
        raise OperationRunError(
            "unsupported-request-version",
            "Operation request version is not supported.",
        )
    raw_tasks = request.get("tasks")
    if not isinstance(raw_tasks, list):
        raise OperationRunError("invalid-request", "Operation tasks are invalid.")
    if not raw_tasks:
        raise OperationRunError(
            "invalid-request", "Operation must include at least one task."
        )
    parsed = []
    for raw in raw_tasks:
        if not isinstance(raw, dict):
            raise OperationRunError(
                "invalid-request", "Operation tasks are invalid."
            )
        name = raw.get("name")
        body = raw.get("body")
        imports = raw.get("imports", [])
        if (
            not isinstance(name, str)
            or not isinstance(body, str)
            or not isinstance(imports, list)
            or not all(isinstance(item, str) for item in imports)
        ):
            raise OperationRunError(
                "invalid-request", "Operation tasks are invalid."
            )
        parsed.append(
            sandbox.TaskSpec(name=name, body=body, imports=list(imports))
        )
    return tuple(parsed)


def _write_chunk(reader, path: Path, limit: int) -> int:
    count = 0
    try:
        output = path.open("wb")
    except OSError as exc:
        raise OperationRunError(
            "candidate-unwritable",
            "Operation chunk input could not be written.",
        ) from exc
    try:
        with output:
            writer = pymarc.MARCWriter(output)
            while count < limit:
                try:
                    record = next(reader)
                except StopIteration:
                    break
                except OSError as exc:
                    raise OperationRunError(
                        "input-unreadable",
                        "Operation input file could not be read.",
                    ) from exc
                except Exception as exc:
                    raise OperationRunError(
                        "malformed-input", "Input contains invalid MARC data."
                    ) from exc
                if record is None:
                    raise OperationRunError(
                        "malformed-input",
                        "Input contains an unreadable MARC record.",
                    )
                try:
                    writer.write(record)
                except OSError as exc:
                    raise OperationRunError(
                        "candidate-unwritable",
                        "Operation chunk input could not be written.",
                    ) from exc
                except Exception as exc:
                    raise OperationRunError(
                        "malformed-input", "Input contains invalid MARC data."
                    ) from exc
                count += 1
            writer.close(close_fh=False)
    except OperationRunError:
        raise
    except OSError as exc:
        raise OperationRunError(
            "candidate-unwritable",
            "Operation chunk input could not be written.",
        ) from exc
    except Exception as exc:
        raise OperationRunError(
            "malformed-input", "Input contains invalid MARC data."
        ) from exc
    return count


def _validate_chunk_output(
    path: Path,
    *,
    expected_records: int,
    chunk_number: int,
) -> None:
    try:
        if not path.is_file():
            raise OperationRunError(
                "malformed-output",
                f"Chunk {chunk_number} produced no MARC output.",
            )
        store = RecordStore.from_path(path)
        if store.malformed_count():
            raise OperationRunError(
                "malformed-output",
                f"Chunk {chunk_number} produced malformed MARC output.",
            )
        if store.count() != expected_records:
            raise OperationRunError(
                "cardinality-mismatch",
                f"Chunk {chunk_number} changed the number of records.",
            )
        if sum(1 for _ in store.iter_records()) != expected_records:
            raise OperationRunError(
                "malformed-output",
                f"Chunk {chunk_number} produced unreadable MARC output.",
            )
    except OSError as exc:
        raise OperationRunError(
            "output-unreadable",
            f"Chunk {chunk_number} output could not be read.",
        ) from exc


def _append_chunk_output(path: Path, candidate) -> None:
    try:
        output = path.open("rb")
    except OSError as exc:
        raise OperationRunError(
            "output-unreadable", "Chunk output could not be read."
        ) from exc
    try:
        with output:
            shutil.copyfileobj(output, candidate)
    except OSError as exc:
        raise OperationRunError(
            "candidate-unwritable", "Operation candidate could not be written."
        ) from exc


def _log_failed_attempt(lease: operations.Lease, exc: BaseException) -> None:
    details = {
        "operation_id": lease.operation_id,
        "attempt": lease.attempt,
        "error": type(exc).__name__,
    }
    if isinstance(exc, OperationCancelled):
        logger.info("queued operation attempt cancelled: %s", details)
    elif isinstance(exc, OperationRunError):
        details["code"] = exc.code
        logger.warning("queued operation attempt rejected: %s", details)
    else:
        logger.exception("queued operation attempt failed: %s", details)
