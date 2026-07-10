"""Transient find/replace pipeline behind the Quick wizard (TASK-036).

The cataloger fills a small form (tag, subfield, find, replace, regex
toggles); we walk the live :class:`RecordStore`, write the matching
subset to a temp MARC file, ship it through the existing subprocess
sandbox under a one-shot task body emitted by :mod:`task_builder`, and
surface a :class:`task_diff.TaskDiffSummary` as the preview. Preview state
keeps only counts, paths, and the source store revision.

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

import re
import shutil
import tempfile
from dataclasses import dataclass
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
    matched_count: int = 0
    previewed_count: int = 0
    store_id: int | None = None
    store_revision: int | None = None
    diff_summary: Optional[task_diff.TaskDiffSummary] = None
    output_path: Path | None = None
    sandbox_workdir: Path | None = None
    error: Optional[str] = None

    @property
    def changed_count(self) -> int:
        return self.diff_summary.changed_count if self.diff_summary else 0

    @property
    def is_empty(self) -> bool:
        return self.matched_count == 0

    @property
    def preview_cap_triggered(self) -> bool:
        return self.matched_count > self.previewed_count


@dataclass
class BatchReplaceResult:
    """Outcome of an Apply call."""

    applied_count: int = 0
    error: Optional[str] = None

    @property
    def applied(self) -> bool:
        return self.applied_count > 0 and self.error is None


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
    matcher = _matcher_for(request)
    return [
        idx
        for idx, record in enumerate(store.iter_records())
        if _record_matches(record, request, matcher)
    ]


def _matcher_for(request: BatchReplaceRequest):
    if request.regex:
        flags = re.IGNORECASE if request.ignore_case else 0
        return re.compile(request.find, flags)
    return request.find.lower() if request.ignore_case else request.find


def _record_matches(record, request: BatchReplaceRequest, matcher) -> bool:
    for field_obj in record.get_fields(request.tag):
        for haystack in _haystacks_for(field_obj, request.subfield):
            if request.regex:
                if matcher.search(haystack):
                    return True
            else:
                candidate = haystack.lower() if request.ignore_case else haystack
                if matcher in candidate:
                    return True
    return False


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


def _write_matching_subset(
    store,
    request: BatchReplaceRequest,
    path: Path,
    *,
    limit: int | None = None,
) -> int:
    """Stream matching records to ``path`` and return the full match count."""
    matcher = _matcher_for(request)
    matched_count = 0
    with path.open("wb") as fh:
        writer = pymarc.MARCWriter(fh)
        for record in store.iter_records():
            if not _record_matches(record, request, matcher):
                continue
            matched_count += 1
            if limit is None or matched_count <= limit:
                writer.write(record)
    return matched_count


def _count_records(path: Path) -> int:
    with Path(path).open("rb") as fh:
        return sum(
            record is not None
            for record in pymarc.MARCReader(
                fh, to_unicode=True, permissive=True
            )
        )


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

    source_revision = store.revision
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-batch-replace-"))
    subset_path = workdir / "subset.mrc"
    try:
        matched_count = _write_matching_subset(
            store,
            request,
            subset_path,
            limit=MAX_PREVIEW_MATCHES,
        )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    previewed_count = min(matched_count, MAX_PREVIEW_MATCHES)
    if matched_count == 0:
        shutil.rmtree(workdir, ignore_errors=True)
        return BatchReplacePreview(
            request=request,
            store_id=id(store),
            store_revision=source_revision,
        )

    try:
        rendered = task_builder.render_ops_to_python([_operation_for(request)])
        spec = sandbox.TaskSpec(
            name="batch-find-replace",
            body=rendered["body"],
            imports=list(rendered["imports"]),
        )
        sandbox_result = sandbox.run_tasks_subprocess(
            [spec], input_path=subset_path, tmp_dir=workdir,
        )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise

    if sandbox_result.timed_out or sandbox_result.returncode != 0:
        return BatchReplacePreview(
            request=request,
            matched_count=matched_count,
            previewed_count=previewed_count,
            store_id=id(store),
            store_revision=source_revision,
            output_path=sandbox_result.output_path,
            sandbox_workdir=workdir,
            error=(
                "Sandbox timed out — try fewer matches."
                if sandbox_result.timed_out
                else f"Sandbox exited with code {sandbox_result.returncode}: "
                f"{(sandbox_result.stderr or '').strip()[:300]}"
            ),
        )

    try:
        output_count = _count_records(sandbox_result.output_path)
    except Exception as exc:  # noqa: BLE001
        return BatchReplacePreview(
            request=request,
            matched_count=matched_count,
            previewed_count=previewed_count,
            store_id=id(store),
            store_revision=source_revision,
            output_path=sandbox_result.output_path,
            sandbox_workdir=workdir,
            error=f"Could not parse sandbox output: {exc}",
        )

    if output_count != previewed_count:
        return BatchReplacePreview(
            request=request,
            matched_count=matched_count,
            previewed_count=previewed_count,
            store_id=id(store),
            store_revision=source_revision,
            output_path=sandbox_result.output_path,
            sandbox_workdir=workdir,
            error=(
                f"Sandbox returned {output_count} records for "
                f"{previewed_count} sandboxed inputs — refusing to "
                "apply a mismatched batch."
            ),
        )

    try:
        summary = task_diff.compute_task_diff(
            subset_path, sandbox_result.output_path
        )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return BatchReplacePreview(
        request=request,
        matched_count=matched_count,
        previewed_count=previewed_count,
        store_id=id(store),
        store_revision=source_revision,
        diff_summary=summary,
        output_path=sandbox_result.output_path,
        sandbox_workdir=workdir,
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_preview(store, preview: BatchReplacePreview) -> BatchReplaceResult:
    """Stream a fresh full transform and atomically adopt it."""
    if preview.error:
        return BatchReplaceResult(error=f"Preview is in error state: {preview.error}")
    if preview.is_empty:
        return BatchReplaceResult(error="No matched records to apply.")
    if preview.store_id != id(store) or preview.store_revision != store.revision:
        return BatchReplaceResult(error="Batch changed since preview.")

    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-batch-replace-apply-"))
    try:
        subset_path = workdir / "subset.mrc"
        matched_count = _write_matching_subset(
            store, preview.request, subset_path
        )
        if matched_count != preview.matched_count:
            return BatchReplaceResult(error="Batch changed since preview.")

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
            return BatchReplaceResult(
                error="Sandbox timed out during apply — try a narrower query."
            )
        if sandbox_result.returncode != 0:
            return BatchReplaceResult(
                error=(
                    f"Sandbox exited with code {sandbox_result.returncode}: "
                    f"{(sandbox_result.stderr or '').strip()[:300]}"
                )
            )
        output_count = _count_records(sandbox_result.output_path)
        if output_count != matched_count:
            return BatchReplaceResult(
                error=(
                    f"Apply sandbox returned {output_count} records for "
                    f"{matched_count} matched inputs — refusing to commit "
                    "a mismatched batch."
                )
            )

        merged_path = workdir / "merged.mrc"
        applied_count = _merge_transformed_matches(
            store,
            preview.request,
            sandbox_result.output_path,
            merged_path,
        )
        store.replace_from_path(merged_path)
        return BatchReplaceResult(applied_count=applied_count)
    except Exception as exc:  # noqa: BLE001
        return BatchReplaceResult(error=f"Could not apply sandbox output: {exc}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _merge_transformed_matches(
    store,
    request: BatchReplaceRequest,
    transformed_path: Path,
    output_path: Path,
) -> int:
    matcher = _matcher_for(request)
    applied_count = 0
    with transformed_path.open("rb") as transformed_fh, output_path.open(
        "wb"
    ) as output_fh:
        transformed = iter(pymarc.MARCReader(
            transformed_fh, to_unicode=True, permissive=True
        ))
        writer = pymarc.MARCWriter(output_fh)
        for record in store.iter_records():
            if _record_matches(record, request, matcher):
                replacement = next(transformed, None)
                if replacement is None:
                    raise ValueError("sandbox output ended before all matches")
                writer.write(replacement)
                applied_count += 1
            else:
                writer.write(record)
        if next(transformed, None) is not None:
            raise ValueError("sandbox output contains extra records")
    return applied_count


def cleanup_preview(preview: BatchReplacePreview | None) -> None:
    workdir = getattr(preview, "sandbox_workdir", None)
    if workdir is None:
        return
    shutil.rmtree(workdir, ignore_errors=True)
