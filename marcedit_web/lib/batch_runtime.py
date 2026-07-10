"""Process-wide admission control and telemetry for heavy batch work."""

from __future__ import annotations

import json
import logging
import os
import resource
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("marcedit_web.performance")

_DEFAULT_MAX_CONCURRENT_BATCHES = 2
_GATE_LOCK = threading.Lock()
_GATE: threading.BoundedSemaphore | None = None
_GATE_CAPACITY: int | None = None


def _configured_capacity() -> int:
    raw = os.environ.get("MARCEDIT_WEB_MAX_CONCURRENT_BATCHES", "").strip()
    if not raw:
        return _DEFAULT_MAX_CONCURRENT_BATCHES
    try:
        capacity = int(raw)
        if capacity < 1:
            raise ValueError
    except ValueError:
        logger.warning(
            "invalid MARCEDIT_WEB_MAX_CONCURRENT_BATCHES=%r; using %d",
            raw,
            _DEFAULT_MAX_CONCURRENT_BATCHES,
        )
        return _DEFAULT_MAX_CONCURRENT_BATCHES
    return capacity


def _gate() -> tuple[threading.BoundedSemaphore, int]:
    global _GATE, _GATE_CAPACITY
    with _GATE_LOCK:
        if _GATE is None:
            _GATE_CAPACITY = _configured_capacity()
            _GATE = threading.BoundedSemaphore(_GATE_CAPACITY)
        return _GATE, int(_GATE_CAPACITY)


def max_concurrent_batches() -> int:
    """Return the process-wide batch admission capacity."""
    return _gate()[1]


@contextmanager
def batch_slot(operation: str) -> Iterator[None]:
    """Wait for a heavy-operation slot and always release it afterward."""
    gate, capacity = _gate()
    started = time.perf_counter()
    gate.acquire()
    wait_ms = (time.perf_counter() - started) * 1000
    _log_performance(
        {
            "operation": operation,
            "phase": "admission",
            "outcome": "acquired",
            "capacity": capacity,
            "wait_ms": round(wait_ms, 3),
        }
    )
    try:
        yield
    finally:
        gate.release()


@contextmanager
def measure_operation(operation: str, **dimensions: Any) -> Iterator[None]:
    """Log elapsed time, outcome, dimensions, and normalized peak RSS."""
    started = time.perf_counter()
    outcome = "ok"
    error_type: str | None = None
    try:
        yield
    except BaseException as exc:
        outcome = "error"
        error_type = type(exc).__name__
        raise
    finally:
        event = {
            "operation": operation,
            **dimensions,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "outcome": outcome,
            "peak_rss_bytes": peak_rss_bytes(),
        }
        if error_type is not None:
            event["error_type"] = error_type
        _log_performance(event)


def peak_rss_bytes() -> int:
    """Return ``ru_maxrss`` normalized to bytes across Linux and macOS."""
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _log_performance(event: dict[str, Any]) -> None:
    logger.info(
        "batch-performance %s",
        json.dumps(event, sort_keys=True, separators=(",", ":"), default=str),
        extra={"batch_performance": event},
    )


def _reset_gate_for_tests() -> None:
    """Reset lazy process state; only safe when no batch slot is active."""
    global _GATE, _GATE_CAPACITY
    with _GATE_LOCK:
        _GATE = None
        _GATE_CAPACITY = None
