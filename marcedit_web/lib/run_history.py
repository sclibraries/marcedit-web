"""Per-session Tasks run history.

After every sandboxed Tasks run, the page appends a
:class:`TaskRunRecord` to ``st.session_state["task_run_history"]``.
A small evict-oldest helper keeps the list capped (default 5) so
sandbox workdirs don't accumulate without bound across a long
cataloger session.

The history is **per-session, in memory**: closing the tab drops it.
The append-only JSONL audit log (:mod:`marcedit_web.lib.audit`)
captures a ``task-run-completed`` event on every completed run, so
operations / SIEM keeps a record even after the session record
evicts.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_HISTORY_CAP = 5


@dataclass
class TaskRunRecord:
    """One Tasks-page run.

    ``input_path`` / ``output_path`` point at the sandbox workdir's
    ``input.mrc`` / ``output.mrc`` files. The history renderer reads
    bytes lazily on download-button click so a 200 MB run doesn't pin
    Python memory across reruns.
    """

    timestamp: str          # ISO UTC, no fractional seconds
    user: str
    input_filename: Optional[str]
    task_names: list[str] = field(default_factory=list)
    input_record_count: int = 0
    output_record_count: int = 0
    changed_count: int = 0
    error_count: int = 0
    timed_out: bool = False
    sandbox_returncode: int = 0
    # Paths to the sandbox workdir's in/out files. Optional because
    # an early failure may leave one or both unwritten.
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    # The sandbox workdir is the parent of input/output. Tracked
    # separately so evict-and-clean can remove it wholesale.
    workdir: Optional[str] = None


def append_run(
    history: list[TaskRunRecord],
    record: TaskRunRecord,
    *,
    cap: int = DEFAULT_HISTORY_CAP,
) -> tuple[list[TaskRunRecord], list[TaskRunRecord]]:
    """Append ``record`` and evict oldest entries if over the cap.

    Pure function — the caller passes in the current history list
    and gets back ``(new_history, evicted)``. The render layer then
    cleans up each evicted entry's workdir (the bytes on disk).

    Newest entries land at the END of the list. Eviction takes from
    the front (oldest).
    """
    combined = list(history) + [record]
    if len(combined) <= cap:
        return combined, []
    keep_from = len(combined) - cap
    evicted = combined[:keep_from]
    return combined[keep_from:], evicted


def cleanup_workdirs(records: list[TaskRunRecord]) -> None:
    """Remove the workdirs of ``records`` (best-effort).

    Called by the render layer after an ``append_run`` returns
    evicted entries. A missing or already-cleaned workdir is fine —
    just suppressed.
    """
    for r in records:
        if not r.workdir:
            continue
        try:
            shutil.rmtree(r.workdir, ignore_errors=True)
        except OSError:
            pass
