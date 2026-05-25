"""Pre-download diff review for the Tasks run flow.

After the sandbox finishes, the cataloger wants to verify *what
changed* before exporting the new ``.mrc``. This module pairs input
and output records by position (the sandbox driver writes exactly
one output record per input record, including the original on
exception), fingerprints both sides, and emits a structured summary
the Tasks page can render.

The dedicated Diff page handles arbitrary cross-file pairings via
match keys; that's the right tool when keys are needed. This module
is intentionally simpler — positional pairing because the sandbox
preserves order, no match-key configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from . import marc_diff


# Cap how many per-record diffs we materialize for the UI. A delete-029
# task that touches every record in a 100K-record batch would otherwise
# render 100K diff cards — the cataloger wants a representative sample,
# not all of them. Adjustable if a use case appears.
DEFAULT_DIFF_CAP = 200


@dataclass
class PerRecordDiff:
    """One changed record's structured diff."""

    record_index: int            # 0-based position in the batch
    identifier: str | None       # the 001 value when present, else None
    rows: list[tuple[str, str, marc_diff.DiffStatus]]


@dataclass
class TaskDiffSummary:
    """Aggregate + per-record diff between a task run's input and output."""

    total_in: int = 0
    total_out: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    # Per-tag rollup. Keyed by 3-char tag string.
    per_tag_added: dict[str, int] = field(default_factory=dict)
    per_tag_deleted: dict[str, int] = field(default_factory=dict)
    per_tag_modified: dict[str, int] = field(default_factory=dict)
    # Per-record drill-down, capped at DEFAULT_DIFF_CAP entries.
    per_record_diffs: list[PerRecordDiff] = field(default_factory=list)
    # True when changed_count > len(per_record_diffs) — the UI surfaces
    # this so the cataloger knows the list is a sample, not exhaustive.
    cap_triggered: bool = False


def compute_task_diff(
    input_path: Path,
    output_bytes: bytes,
    *,
    diff_cap: int = DEFAULT_DIFF_CAP,
) -> TaskDiffSummary:
    """Walk input and output in parallel; return a structured summary.

    ``input_path`` is the on-disk MRC the sandbox read (typically
    ``sandbox_workdir/input.mrc``). ``output_bytes`` is the
    ``SandboxResult.records_bytes`` blob the child produced. Both are
    iterated lazily — the input via a file read, the output via the
    in-memory bytes — so this stays O(records) in memory cost.

    Pairing is positional because the sandbox writes one output record
    per input record. A task that "drops" a record actually writes the
    original record on exception, so the cardinality matches.
    """
    summary = TaskDiffSummary()
    input_data = input_path.read_bytes()

    in_iter = _iter_records_safe(input_data)
    out_iter = _iter_records_safe(output_bytes)

    while True:
        in_pair = next(in_iter, None)
        out_pair = next(out_iter, None)
        if in_pair is None and out_pair is None:
            break
        if in_pair is None:
            summary.total_out += 1
            continue
        if out_pair is None:
            summary.total_in += 1
            continue

        _, in_bytes = in_pair
        _, out_bytes = out_pair
        summary.total_in += 1
        summary.total_out += 1

        # Fast-path: same fingerprint = no change. Excluding NO tags
        # here (default excludes 001/005 — but for task diffs the user
        # cares about everything, including a 005 update).
        in_fp = marc_diff.fingerprint_record(in_bytes, exclude_tags=frozenset())
        out_fp = marc_diff.fingerprint_record(out_bytes, exclude_tags=frozenset())
        if in_fp == out_fp:
            summary.unchanged_count += 1
            continue

        summary.changed_count += 1
        rows = marc_diff.field_diff(in_bytes, out_bytes)
        _tally_per_tag(rows, summary)

        if len(summary.per_record_diffs) < diff_cap:
            summary.per_record_diffs.append(PerRecordDiff(
                record_index=summary.total_in - 1,
                identifier=_extract_001(rows),
                rows=rows,
            ))
        else:
            summary.cap_triggered = True

    return summary


def _iter_records_safe(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield ``(offset, record_bytes)`` and swallow late-trailer truncation.

    ``marc_diff._iter_records`` raises ``ValueError`` on a truncated
    blob — fine for indexing on upload, but here we want to walk as
    far as we can without aborting the diff.
    """
    try:
        yield from marc_diff._iter_records(data)
    except ValueError:
        return


def _tally_per_tag(
    rows: list[tuple[str, str, marc_diff.DiffStatus]],
    summary: TaskDiffSummary,
) -> None:
    """Count added / removed / changed by tag into the summary buckets."""
    for old_line, new_line, status in rows:
        if status == "unchanged":
            continue
        tag = _line_tag(new_line) or _line_tag(old_line)
        if not tag:
            continue
        if status == "added":
            summary.per_tag_added[tag] = summary.per_tag_added.get(tag, 0) + 1
        elif status == "removed":
            summary.per_tag_deleted[tag] = summary.per_tag_deleted.get(tag, 0) + 1
        else:  # changed
            summary.per_tag_modified[tag] = summary.per_tag_modified.get(tag, 0) + 1


def _line_tag(line: str) -> str | None:
    """Extract the 3-char tag from a ``=NNN  data…`` rendered field line.

    Returns ``None`` for the leader row (``=LDR ...``) and for empty
    lines emitted by the aligned-diff padding.
    """
    if not line or not line.startswith("="):
        return None
    head = line[1:4]
    if head == "LDR":
        return None
    if len(head) != 3:
        return None
    return head


def _extract_001(rows: list[tuple[str, str, marc_diff.DiffStatus]]) -> str | None:
    """Return the (possibly post-change) 001 value when present."""
    for _old, new, _status in rows:
        if new.startswith("=001  "):
            return new[6:].strip() or None
    for old, _new, _status in rows:
        if old.startswith("=001  "):
            return old[6:].strip() or None
    return None
