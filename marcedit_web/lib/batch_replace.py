"""Transient find/replace pipeline behind the Quick wizard (TASK-036).

The cataloger fills a small form (tag, subfield, find, replace, regex
toggles); we walk the live :class:`RecordStore`, write the matching
subset to a temp MARC file, ship it through the existing subprocess
sandbox under a one-shot task body emitted by
:mod:`task_builder`, and surface a :class:`task_diff.TaskDiffSummary`
as the preview. Apply re-fingerprints each matched record against the
live store and refuses if anything has drifted since the preview.

No saved task file is created; the task body lives only in the
sandbox driver's exec call. The wizard reuses the audit + diff
infrastructure that already exists for the regular Tasks run flow.

Why a separate module instead of layering on the form-builder:
the form-builder is built around persisted, named tasks; the wizard
is one-shot and doesn't need editor/sandbox/run-history coupling.
Keeping the wiring in one module also keeps the Tasks-page render
function from growing another ~200 lines.
"""

from __future__ import annotations

import hashlib
import io
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import pymarc

from . import sandbox, task_builder, task_diff
from .task_builder import Operation


# ---------------------------------------------------------------------------
# Request / result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchReplaceRequest:
    """The cataloger's form input, normalized."""

    tag: str
    subfield: Optional[str]   # 1-char code or None
    find: str
    replace: str
    regex: bool = False
    ignore_case: bool = False


@dataclass
class BatchReplacePreview:
    """Outcome of a non-mutating preview pass."""

    request: BatchReplaceRequest
    matched_indices: list[int]                 # 0-based RecordStore indices
    fingerprints: dict[int, str]               # index → sha256 of record bytes
    diff_summary: Optional[task_diff.TaskDiffSummary] = None
    output_records: list[pymarc.Record] = field(default_factory=list)
    sandbox_workdir: Optional[str] = None
    error: Optional[str] = None

    @property
    def changed_count(self) -> int:
        return self.diff_summary.changed_count if self.diff_summary else 0

    @property
    def is_empty(self) -> bool:
        return not self.matched_indices


@dataclass
class BatchReplaceResult:
    """Outcome of an Apply call."""

    applied_indices: list[int] = field(default_factory=list)
    stale_indices: list[int] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def applied(self) -> bool:
        return bool(self.applied_indices) and not self.stale_indices


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_request(request: BatchReplaceRequest) -> Optional[str]:
    """Return a cataloger-readable error message, or ``None``."""
    if not (request.tag or "").strip():
        return "Tag is required."
    if request.subfield and len(request.subfield) != 1:
        return "Subfield code must be a single character."
    if not (request.find or ""):
        return "Find text is required."
    if request.regex:
        flags = re.IGNORECASE if request.ignore_case else 0
        try:
            re.compile(request.find, flags)
        except re.error as exc:
            return f"Invalid regex: {exc}"
    return None


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _haystacks_for(
    field_obj: pymarc.Field, subfield: Optional[str]
) -> Iterator[str]:
    """Yield the strings to search against for a given field + subfield filter."""
    if field_obj.is_control_field():
        if subfield is None:
            yield field_obj.data or ""
        return
    if subfield is not None:
        for value in field_obj.get_subfields(subfield):
            yield value
        return
    for sf in field_obj.subfields:
        yield sf.value


def matched_indices_for(store, request: BatchReplaceRequest) -> list[int]:
    """Return the 0-based indices of records whose target matches the find.

    A record counts as a match if **any** field with ``request.tag`` has
    a haystack (subfield value, or full ``.data`` for control fields)
    that contains the find text (regex or literal, case-sensitive or
    not).
    """
    compiled = None
    if request.regex:
        flags = re.IGNORECASE if request.ignore_case else 0
        compiled = re.compile(request.find, flags)
    needle = request.find
    needle_cmp = needle.lower() if request.ignore_case else needle

    matched: list[int] = []
    for idx, record in enumerate(store.iter_records()):
        if not record.get_fields(request.tag):
            continue
        for field_obj in record.get_fields(request.tag):
            hit = False
            for hay in _haystacks_for(field_obj, request.subfield):
                if compiled is not None:
                    if compiled.search(hay):
                        hit = True
                        break
                else:
                    hay_cmp = hay.lower() if request.ignore_case else hay
                    if needle_cmp in hay_cmp:
                        hit = True
                        break
            if hit:
                matched.append(idx)
                break
    return matched


# ---------------------------------------------------------------------------
# Fingerprint (stale-preview detection)
# ---------------------------------------------------------------------------


def fingerprint_record(record: pymarc.Record) -> str:
    """SHA-256 of ``record.as_marc()`` bytes — the stale-detection key."""
    return hashlib.sha256(record.as_marc()).hexdigest()


def _fingerprints_for(store, indices: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for idx in indices:
        rec = store.get(idx)
        if rec is None:
            continue
        out[idx] = fingerprint_record(rec)
    return out


# ---------------------------------------------------------------------------
# Build + run the transient task
# ---------------------------------------------------------------------------


def _operation_for(request: BatchReplaceRequest) -> Operation:
    """Pick the form-builder op kind that corresponds to the request."""
    if request.subfield:
        return Operation(
            kind="subfield-replace",
            params={
                "tag": request.tag,
                "code": request.subfield,
                "find": request.find,
                "replace": request.replace,
                "regex": bool(request.regex),
                "ignore_case": bool(request.ignore_case),
            },
        )
    # No subfield filter — regex over field data. Literal mode is
    # emulated via ``re.escape`` so the same op handles both.
    pattern = request.find if request.regex else re.escape(request.find)
    return Operation(
        kind="replace-field-data-by-regex",
        params={
            "tag": request.tag,
            "pattern": pattern,
            "replacement": request.replace,
            "ignore_case": bool(request.ignore_case),
        },
    )


def _write_subset(store, indices: list[int], path: Path) -> None:
    """Stream the matched records to ``path`` as a binary MARC subset."""
    with path.open("wb") as fh:
        writer = pymarc.MARCWriter(fh)
        for idx in indices:
            rec = store.get(idx)
            if rec is not None:
                writer.write(rec)


def build_preview(store, request: BatchReplaceRequest) -> BatchReplacePreview:
    """Run the request on matched records in the sandbox; return the preview.

    Never mutates ``store``. Raises ``ValueError`` for an invalid
    request shape (bad regex, empty tag, etc.); sandbox / parse errors
    land on the returned preview's ``error`` field so the wizard can
    surface them in the UI.
    """
    err = validate_request(request)
    if err is not None:
        raise ValueError(err)

    matched = matched_indices_for(store, request)
    if not matched:
        return BatchReplacePreview(
            request=request,
            matched_indices=[],
            fingerprints={},
        )

    fingerprints = _fingerprints_for(store, matched)
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-batch-replace-"))
    subset_path = workdir / "subset.mrc"
    _write_subset(store, matched, subset_path)

    rendered = task_builder.render_ops_to_python([_operation_for(request)])
    spec = sandbox.TaskSpec(
        name="batch-find-replace",
        body=rendered["body"],
        imports=list(rendered["imports"]),
    )
    sandbox_result = sandbox.run_tasks_subprocess(
        [spec], input_path=subset_path, tmp_dir=workdir,
    )

    if sandbox_result.timed_out or sandbox_result.returncode != 0:
        return BatchReplacePreview(
            request=request,
            matched_indices=matched,
            fingerprints=fingerprints,
            sandbox_workdir=str(workdir),
            error=(
                "Sandbox timed out — try fewer matches."
                if sandbox_result.timed_out
                else f"Sandbox exited with code {sandbox_result.returncode}: "
                f"{(sandbox_result.stderr or '').strip()[:300]}"
            ),
        )

    try:
        output_records = list(pymarc.MARCReader(
            io.BytesIO(sandbox_result.records_bytes),
            to_unicode=True, permissive=True,
        ))
    except Exception as exc:  # noqa: BLE001
        return BatchReplacePreview(
            request=request,
            matched_indices=matched,
            fingerprints=fingerprints,
            sandbox_workdir=str(workdir),
            error=f"Could not parse sandbox output: {exc}",
        )

    # Drop None entries (malformed records in pymarc's eyes).
    output_records = [r for r in output_records if r is not None]

    # Pair count check — sandbox preserves order and writes one
    # output per input even on per-record exception, so the counts
    # should match. If they don't, something subtle went wrong;
    # surface as an error rather than silently truncate.
    if len(output_records) != len(matched):
        return BatchReplacePreview(
            request=request,
            matched_indices=matched,
            fingerprints=fingerprints,
            sandbox_workdir=str(workdir),
            error=(
                f"Sandbox returned {len(output_records)} records for "
                f"{len(matched)} matched inputs — refusing to apply a "
                "mismatched batch."
            ),
        )

    summary = task_diff.compute_task_diff(subset_path, sandbox_result.records_bytes)
    return BatchReplacePreview(
        request=request,
        matched_indices=matched,
        fingerprints=fingerprints,
        diff_summary=summary,
        output_records=output_records,
        sandbox_workdir=str(workdir),
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_preview(store, preview: BatchReplacePreview) -> BatchReplaceResult:
    """Commit ``preview.output_records`` back to ``store`` at the matched indices.

    Refuses (with a stale-indices list) if any matched record's
    on-disk fingerprint has changed since the preview was built —
    the cataloger probably edited a matched record in another tab
    and the preview no longer reflects what they'd actually be
    overwriting.
    """
    if preview.error:
        return BatchReplaceResult(error=f"Preview is in error state: {preview.error}")
    if preview.is_empty:
        return BatchReplaceResult(error="No matched records to apply.")
    if len(preview.output_records) != len(preview.matched_indices):
        return BatchReplaceResult(
            error="Preview output is inconsistent with matched indices — "
                  "rebuild the preview and try again.",
        )

    stale: list[int] = []
    for idx, expected_fp in preview.fingerprints.items():
        rec = store.get(idx)
        if rec is None:
            stale.append(idx)
            continue
        if fingerprint_record(rec) != expected_fp:
            stale.append(idx)
    if stale:
        return BatchReplaceResult(
            applied_indices=[],
            stale_indices=stale,
            error=(
                f"Stale preview — {len(stale)} record(s) have changed since "
                "the preview was built. Rebuild the preview and try again."
            ),
        )

    for idx, new_record in zip(preview.matched_indices, preview.output_records):
        store.replace(idx, new_record)
    return BatchReplaceResult(
        applied_indices=list(preview.matched_indices),
        stale_indices=[],
    )
