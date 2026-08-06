"""Shared in-page status and progress rendering for long operations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import streamlit as st


COMPLETION_KEY = "operation_activity_completion"
_PROGRESS_STEP = 250


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

    def phase(self, label: str, message: str) -> None:
        """Update the current phase label and human-readable message."""
        self.phase_label = label
        self._status.update(label=label, state="running", expanded=True)
        self._message.markdown(message)

    def progress_callback(self, processed: int, total: int) -> None:
        """Render throttled record progress while preserving the old cadence."""
        if self._progress is None or total <= 0:
            self._message.write("Progress unavailable — processing records…")
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
        self._status.update(label=label, state=state, expanded=False)
        self._message.markdown(message)
        st.session_state[COMPLETION_KEY] = {
            "operation_id": self.operation_id,
            "state": state,
            "label": label,
            "message": message,
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
    st.write(f"{phase}…")
    progress = st.progress(0.0) if total is not None and total > 0 else None
    message = st.empty()
    activity = ActivityHandle(
        operation_id,
        status,
        message,
        progress,
        _total=total,
        phase_label=phase,
    )
    try:
        yield activity
    finally:
        pass


def render_completion(operation_id: str) -> bool:
    """Replay a matching completion summary in a collapsed status panel."""
    summary = st.session_state.get(COMPLETION_KEY)
    if not isinstance(summary, dict) or summary.get("operation_id") != operation_id:
        return False
    status = st.status(str(summary.get("label", "Operation")), expanded=False)
    status.update(
        label=str(summary.get("label", "Operation")),
        state=str(summary.get("state", "complete")),
        expanded=False,
    )
    st.write(str(summary.get("message", "")))
    return True


def clear_completion(operation_id: str | None = None) -> None:
    """Clear the completion summary, optionally only for one operation."""
    if operation_id is None:
        st.session_state.pop(COMPLETION_KEY, None)
        return
    summary = st.session_state.get(COMPLETION_KEY)
    if isinstance(summary, dict) and summary.get("operation_id") == operation_id:
        st.session_state.pop(COMPLETION_KEY, None)
