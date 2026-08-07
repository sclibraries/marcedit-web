"""Shared in-page status and progress rendering for long operations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import streamlit as st


COMPLETION_KEY = "operation_activity_completion"
_PROGRESS_STEP = 250
MAX_LABEL_LENGTH = 160
MAX_MESSAGE_LENGTH = 1000
_PROGRESS_UNAVAILABLE = "Progress unavailable — processing records…"
_TRACEBACK_MARKER = "Traceback (most recent call last)"


def _bounded_plain_string(
    value: Any,
    *,
    limit: int,
    fallback: str,
) -> str:
    """Return a short, plain summary string without exception diagnostics."""
    if isinstance(value, BaseException):
        return fallback
    if not isinstance(value, str):
        value = str(value)
    if _TRACEBACK_MARKER in value:
        return fallback
    value = " ".join(value.split())
    return value[:limit] or fallback


@dataclass
class ActivityHandle:
    """Mutable presentation state for one in-page operation activity panel."""

    operation_id: str
    _status: Any
    _message: Any
    _progress: Any | None
    _last_rendered: int = 0
    _total: int | None = None
    phase_label: str = "Processing"
    _progress_unavailable_rendered: bool = False

    def phase(self, label: str, message: str) -> None:
        """Update the current phase label and human-readable message."""
        self.phase_label = label
        self._status.update(label=label, state="running", expanded=True)
        self._message.markdown(_bounded_plain_string(
            message, limit=MAX_MESSAGE_LENGTH, fallback="Processing…"
        ))

    def write(self, message: str) -> None:
        """Write bounded content inside the status container."""
        self._status.write(
            _bounded_plain_string(
                message, limit=MAX_MESSAGE_LENGTH, fallback="Processing…"
            )
        )

    def progress_callback(self, processed: int, total: int | None) -> None:
        """Render throttled record progress while preserving the old cadence."""
        if self._progress is None or total is None or total <= 0:
            if not self._progress_unavailable_rendered:
                self._message.write(_PROGRESS_UNAVAILABLE)
                self._progress_unavailable_rendered = True
            return

        if processed <= self._last_rendered:
            return
        if (
            processed != 1
            and processed != total
            and processed % _PROGRESS_STEP != 0
        ):
            return

        self._last_rendered = processed
        self._progress.progress(processed / total)
        self._message.markdown(
            f"{self._current_phase} record {processed:,} of {total:,}…"
        )

    def complete(self, label: str, message: str) -> None:
        """Mark the panel complete and retain its bounded rerun summary."""
        self._finish("complete", label, message)

    def fail(self, label: str, message: str) -> None:
        """Mark the panel failed and retain its bounded rerun summary."""
        self._finish("error", label, message)

    def _finish(self, state: str, label: str, message: str) -> None:
        bounded_label = _bounded_plain_string(
            label, limit=MAX_LABEL_LENGTH, fallback="Operation"
        )
        bounded_message = _bounded_plain_string(
            message, limit=MAX_MESSAGE_LENGTH, fallback="Operation failed."
        )
        self._status.update(label=bounded_label, state=state, expanded=False)
        self._message.empty()
        if self._progress is not None:
            self._progress.empty()
        self._status.write(bounded_message)
        st.session_state[COMPLETION_KEY] = {
            "operation_id": self.operation_id,
            "state": state,
            "label": bounded_label,
            "message": bounded_message,
        }

    @property
    def _current_phase(self) -> str:
        return self.phase_label


@contextmanager
def open_activity(
    operation_id: str,
    label: str,
    *,
    phase: str,
    total: int | None = None,
) -> Iterator[ActivityHandle]:
    """Open an expanded activity panel and yield its presentation handle."""
    status = st.status(label, expanded=True)
    status.write(f"{phase}…")
    progress = status.progress(0.0) if total is not None and total > 0 else None
    message = status.empty()
    activity = ActivityHandle(
        operation_id,
        status,
        message,
        progress,
        _total=total,
        phase_label=phase,
    )
    if progress is None:
        message.write(_PROGRESS_UNAVAILABLE)
        activity._progress_unavailable_rendered = True
    try:
        yield activity
    finally:
        pass


def render_completion(operation_id: str) -> bool:
    """Replay a matching completion summary in a collapsed status panel."""
    summary = st.session_state.get(COMPLETION_KEY)
    if not isinstance(summary, dict) or summary.get("operation_id") != operation_id:
        return False
    label = _bounded_plain_string(
        summary.get("label"), limit=MAX_LABEL_LENGTH, fallback="Operation"
    )
    message = _bounded_plain_string(
        summary.get("message"), limit=MAX_MESSAGE_LENGTH, fallback=""
    )
    state = summary.get("state")
    if state not in {"complete", "error"}:
        state = "complete"
    status = st.status(label, expanded=False)
    status.update(
        label=label,
        state=state,
        expanded=False,
    )
    status.write(message)
    return True


def clear_completion(operation_id: str | None = None) -> None:
    """Clear the completion summary, optionally only for one operation."""
    if operation_id is None:
        st.session_state.pop(COMPLETION_KEY, None)
        return
    summary = st.session_state.get(COMPLETION_KEY)
    if isinstance(summary, dict) and summary.get("operation_id") == operation_id:
        st.session_state.pop(COMPLETION_KEY, None)
