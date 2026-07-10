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


# TASK-046: preview only sandbox-runs the first N matches so a broad
# query on a 100K-record batch doesn't hang for minutes. Apply still
# runs over the full matched set; the cap is preview-only.
MAX_PREVIEW_MATCHES = 500


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
    # TASK-046: snapshot of which loaded batch this preview was built
    # against. Apply refuses if the cataloger swapped the active file
    # between Preview and Apply (cataloger sees a clear "batch
    # changed" message instead of a fingerprint-accidentally-matches
    # mutation).
    batch_identity: Optional[tuple[str, int]] = None  # (filename, count)
    # TASK-046: True when the sandbox-side preview was capped at
    # MAX_PREVIEW_MATCHES. Apply still operates on the full matched
    # set; the UI surfaces "previewing first N of M" to keep the
    # cataloger honest about what they reviewed.
    preview_cap_triggered: bool = False

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


def _batch_identity(store) -> Optional[tuple[str, int]]:
    """Return a stable ``(filename, count)`` snapshot of the active batch.

    Used by build_preview to record which batch a preview was built
    against; apply_preview rejects if the identity has changed.
    """
    if store is None:
        return None
    filename = getattr(store, "filename", None) or "(unnamed)"
    try:
        count = store.count()
    except Exception:  # noqa: BLE001 — defensive in callsite context
        count = -1
    return (filename, count)


def build_preview(store, request: BatchReplaceRequest) -> BatchReplacePreview:
    """Run the request on matched records in the sandbox; return the preview.

    Never mutates ``store``. Raises ``ValueError`` for an invalid
    request shape (bad regex, empty tag, etc.); sandbox / parse errors
    land on the returned preview's ``error`` field so the wizard can
    surface them in the UI.

    TASK-046: the sandbox preview is capped at
    :data:`MAX_PREVIEW_MATCHES`. The cataloger reviews the diff for
    that subset; Apply re-runs the transform against the **full**
    matched set. The cap is a guardrail against the page hanging on
    a query that incidentally matches every record in a 100K batch.
    """
    err = validate_request(request)
    if err is not None:
        raise ValueError(err)

    batch_id = _batch_identity(store)

    matched = matched_indices_for(store, request)
    if not matched:
        return BatchReplacePreview(
            request=request,
            matched_indices=[],
            fingerprints={},
            batch_identity=batch_id,
        )

    # Sandbox-run only the first N matches when the set is large.
    # Apply re-runs against the full matched list — preview is just
    # the cataloger's sample.
    cap_triggered = len(matched) > MAX_PREVIEW_MATCHES
    preview_indices = matched[:MAX_PREVIEW_MATCHES] if cap_triggered else matched

    fingerprints = _fingerprints_for(store, matched)
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-batch-replace-"))
    subset_path = workdir / "subset.mrc"
    _write_subset(store, preview_indices, subset_path)

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
            batch_identity=batch_id,
            preview_cap_triggered=cap_triggered,
            error=(
                "Sandbox timed out — try fewer matches."
                if sandbox_result.timed_out
                else f"Sandbox exited with code {sandbox_result.returncode}: "
                f"{(sandbox_result.stderr or '').strip()[:300]}"
            ),
        )

    try:
        with sandbox_result.output_path.open("rb") as output_fh:
            output_records = list(pymarc.MARCReader(
                output_fh, to_unicode=True, permissive=True,
            ))
    except Exception as exc:  # noqa: BLE001
        return BatchReplacePreview(
            request=request,
            matched_indices=matched,
            fingerprints=fingerprints,
            sandbox_workdir=str(workdir),
            batch_identity=batch_id,
            preview_cap_triggered=cap_triggered,
            error=f"Could not parse sandbox output: {exc}",
        )

    # Drop None entries (malformed records in pymarc's eyes).
    output_records = [r for r in output_records if r is not None]

    # Pair count check — sandbox preserves order and writes one
    # output per input even on per-record exception, so counts
    # should match the SUBSET we sandbox-ran (preview_indices).
    if len(output_records) != len(preview_indices):
        return BatchReplacePreview(
            request=request,
            matched_indices=matched,
            fingerprints=fingerprints,
            sandbox_workdir=str(workdir),
            batch_identity=batch_id,
            preview_cap_triggered=cap_triggered,
            error=(
                f"Sandbox returned {len(output_records)} records for "
                f"{len(preview_indices)} sandboxed inputs — refusing to "
                "apply a mismatched batch."
            ),
        )

    summary = task_diff.compute_task_diff(
        subset_path, sandbox_result.output_path
    )
    return BatchReplacePreview(
        request=request,
        matched_indices=matched,
        fingerprints=fingerprints,
        diff_summary=summary,
        output_records=output_records,
        sandbox_workdir=str(workdir),
        batch_identity=batch_id,
        preview_cap_triggered=cap_triggered,
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_preview(store, preview: BatchReplacePreview) -> BatchReplaceResult:
    """Commit the transform back to ``store`` at the matched indices.

    Defenses in order:

    1. **Preview error state** — refuse outright.
    2. **Empty matched set** — refuse with a clarifying message.
    3. **Batch identity drift** (TASK-046) — if the loaded file
       changed since Preview, the matched indices may now point at
       different records. Refuse and force a fresh preview.
    4. **Record fingerprint drift** — even with the same batch
       loaded, if any matched record was edited (inline editor, a
       different task run, etc.) between Preview and Apply, refuse
       so the cataloger doesn't overwrite work they didn't see.
    5. **Preview was capped** (TASK-046) — when the preview only
       sandbox-ran the first N of M matches, run a fresh sandbox
       over the full matched set before committing.

    Returns a :class:`BatchReplaceResult` indicating success
    (``applied_indices`` populated, ``stale_indices`` empty) or
    refusal (``error`` populated; ``stale_indices`` may carry the
    drifted index list).
    """
    if preview.error:
        return BatchReplaceResult(error=f"Preview is in error state: {preview.error}")
    if preview.is_empty:
        return BatchReplaceResult(error="No matched records to apply.")

    # TASK-046 #2: batch-identity check.
    current_id = _batch_identity(store)
    if preview.batch_identity is not None and current_id != preview.batch_identity:
        prev_name, prev_count = preview.batch_identity
        curr_name, curr_count = current_id or ("(none)", 0)
        return BatchReplaceResult(
            error=(
                f"Batch changed since the preview was built — preview was "
                f"against `{prev_name}` ({prev_count} records); current is "
                f"`{curr_name}` ({curr_count} records). Rebuild the preview "
                "before applying."
            ),
        )

    # Fingerprint drift detection — covers the in-place-edited case.
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

    # TASK-046 #1: when the preview was capped, sandbox-run the full
    # matched set before committing.
    if preview.preview_cap_triggered:
        full_records = _run_sandbox_over_matched(store, preview)
        if isinstance(full_records, str):
            return BatchReplaceResult(error=full_records)
        records_for_apply = full_records
    else:
        if len(preview.output_records) != len(preview.matched_indices):
            return BatchReplaceResult(
                error="Preview output is inconsistent with matched indices — "
                      "rebuild the preview and try again.",
            )
        records_for_apply = preview.output_records

    for idx, new_record in zip(preview.matched_indices, records_for_apply):
        store.replace(idx, new_record)
    return BatchReplaceResult(
        applied_indices=list(preview.matched_indices),
        stale_indices=[],
    )


def _run_sandbox_over_matched(
    store, preview: BatchReplacePreview,
) -> "list[pymarc.Record] | str":
    """Sandbox-run the preview's request over the full matched index set.

    Used at Apply time when the preview-pass capped at
    :data:`MAX_PREVIEW_MATCHES`. Returns a list of output records
    parallel to ``preview.matched_indices`` on success, or an error
    string on failure (sandbox timeout / non-zero exit / output
    parse failure / cardinality mismatch).
    """
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-batch-replace-apply-"))
    subset_path = workdir / "subset.mrc"
    _write_subset(store, preview.matched_indices, subset_path)

    rendered = task_builder.render_ops_to_python(
        [_operation_for(preview.request)]
    )
    spec = sandbox.TaskSpec(
        name="batch-find-replace-apply",
        body=rendered["body"],
        imports=list(rendered["imports"]),
    )
    sandbox_result = sandbox.run_tasks_subprocess(
        [spec], input_path=subset_path, tmp_dir=workdir,
    )

    if sandbox_result.timed_out:
        return "Sandbox timed out during apply — try a narrower query."
    if sandbox_result.returncode != 0:
        return (
            f"Sandbox exited with code {sandbox_result.returncode}: "
            f"{(sandbox_result.stderr or '').strip()[:300]}"
        )

    try:
        with sandbox_result.output_path.open("rb") as output_fh:
            records = list(pymarc.MARCReader(
                output_fh, to_unicode=True, permissive=True,
            ))
    except Exception as exc:  # noqa: BLE001
        return f"Could not parse sandbox output during apply: {exc}"

    records = [r for r in records if r is not None]
    if len(records) != len(preview.matched_indices):
        return (
            f"Apply sandbox returned {len(records)} records for "
            f"{len(preview.matched_indices)} matched inputs — refusing to "
            "commit a mismatched batch."
        )
    return records
