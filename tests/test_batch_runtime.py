"""Admission control and telemetry for large batch operations (TASK-147)."""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest

from marcedit_web.lib import batch_runtime


@pytest.fixture(autouse=True)
def _fresh_gate(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_MAX_CONCURRENT_BATCHES", raising=False)
    batch_runtime._reset_gate_for_tests()
    yield
    batch_runtime._reset_gate_for_tests()


def test_default_gate_capacity_is_two():
    assert batch_runtime.max_concurrent_batches() == 2


def test_gate_capacity_honors_environment_override(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_CONCURRENT_BATCHES", "1")
    batch_runtime._reset_gate_for_tests()

    assert batch_runtime.max_concurrent_batches() == 1


def test_third_operation_waits_until_one_of_two_slots_releases():
    release = threading.Event()
    first_two_entered = threading.Event()
    third_entered = threading.Event()
    entered: list[int] = []
    lock = threading.Lock()

    def _worker(number: int) -> None:
        with batch_runtime.batch_slot(f"operation-{number}"):
            with lock:
                entered.append(number)
                if len(entered) == 2:
                    first_two_entered.set()
                if number == 3:
                    third_entered.set()
            release.wait(timeout=2)

    first = threading.Thread(target=_worker, args=(1,))
    second = threading.Thread(target=_worker, args=(2,))
    third = threading.Thread(target=_worker, args=(3,))
    first.start()
    second.start()
    assert first_two_entered.wait(timeout=1)
    third.start()

    assert not third_entered.wait(timeout=0.1)
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)
    third.join(timeout=1)

    assert third_entered.is_set()
    assert not any(thread.is_alive() for thread in (first, second, third))


def test_slot_is_released_when_operation_raises(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_CONCURRENT_BATCHES", "1")
    batch_runtime._reset_gate_for_tests()

    with pytest.raises(RuntimeError, match="boom"):
        with batch_runtime.batch_slot("failing-operation"):
            raise RuntimeError("boom")

    entered = threading.Event()

    def _next_operation() -> None:
        with batch_runtime.batch_slot("next-operation"):
            entered.set()

    thread = threading.Thread(target=_next_operation)
    thread.start()
    thread.join(timeout=1)

    assert entered.is_set()
    assert not thread.is_alive()


def test_peak_rss_is_normalized_to_bytes_on_linux(monkeypatch):
    monkeypatch.setattr(batch_runtime.sys, "platform", "linux")
    monkeypatch.setattr(
        batch_runtime.resource,
        "getrusage",
        lambda scope: SimpleNamespace(ru_maxrss=2048),
    )

    assert batch_runtime.peak_rss_bytes() == 2048 * 1024


def test_measure_operation_logs_dimensions_and_success(caplog, monkeypatch):
    monkeypatch.setattr(batch_runtime, "peak_rss_bytes", lambda: 123_456)
    caplog.set_level(logging.INFO, logger="marcedit_web.performance")

    with batch_runtime.measure_operation(
        "quick-batch",
        phase="preview",
        records=100_000,
        bytes=25_000_000,
    ):
        pass

    event = caplog.records[-1].batch_performance
    assert event["operation"] == "quick-batch"
    assert event["phase"] == "preview"
    assert event["records"] == 100_000
    assert event["bytes"] == 25_000_000
    assert event["outcome"] == "ok"
    assert event["peak_rss_bytes"] == 123_456
    assert event["elapsed_ms"] >= 0


def test_measure_operation_logs_failure_and_reraises(caplog):
    caplog.set_level(logging.INFO, logger="marcedit_web.performance")

    with pytest.raises(ValueError, match="bad batch"):
        with batch_runtime.measure_operation("saved-task", phase="sandbox"):
            raise ValueError("bad batch")

    event = caplog.records[-1].batch_performance
    assert event["outcome"] == "error"
    assert event["error_type"] == "ValueError"


def test_measure_operation_can_mark_returned_failure(caplog):
    """Result-object errors must not be logged as successful operations."""
    caplog.set_level(logging.INFO, logger="marcedit_web.performance")

    with batch_runtime.measure_operation(
        "quick-replace", phase="apply"
    ) as measurement:
        measurement.mark_error("PreviewRejected")

    event = caplog.records[-1].batch_performance
    assert event["outcome"] == "error"
    assert event["error_type"] == "PreviewRejected"
