"""Sandbox-backed preview and apply candidates for Quick field changes.

The runner deliberately keeps the Streamlit process out of the mutation
path.  A complete :class:`RecordStore` is streamed to a private workspace,
the fixed structured adapter runs in the child process, and only bounded
counts/diff evidence are retained in the preview.  Apply repeats the same
run against the current store and returns an independently owned candidate;
the caller decides when that candidate should be adopted.
"""

from __future__ import annotations

import json
import secrets
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import sandbox, task_diff
from .quick_field_changes import (
    QuickFieldChangeRequest,
    canonical_request_json,
    request_to_payload,
)


_ARTIFACT_PREFIX = "marcedit-web-quick-field-change-"
_OWNERSHIP_MARKER = ".quick-field-change-owner.json"
_OWNERSHIP_KIND = "marcedit-web.quick-field-change.artifact.v1"
_MAX_ERROR_CHARS = 1024
_MAX_ERROR_BYTES = 2048
_REQUIRED_TOTAL_KEYS = (
    "changed_records",
    "unchanged_records",
    "skipped_records",
    "fields_affected",
    "subfields_affected",
)

# A marker alone is not an authority: a caller could copy one into a
# similarly named directory.  Keep the random token in this process too, so
# only workdirs created by this runner can be cleaned up or adopted.
_OWNED_ARTIFACTS: dict[Path, str] = {}


@dataclass
class QuickFieldChangePreview:
    """Immutable request identity and disk-backed preview evidence."""

    request: QuickFieldChangeRequest
    request_json: str
    output_path: Path | None = None
    workdir: Path | None = None
    record_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    fields_affected: int = 0
    subfields_affected: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    store_id: int | None = None
    store_revision: int | None = None
    job_file_id: int | None = None
    job_file_version_id: int | None = None
    error: str | None = None
    # The task diff already caps per-record evidence.  Keeping it on the
    # preview avoids retaining MARC records or a second copy of the batch.
    diff_summary: task_diff.TaskDiffSummary | None = None


@dataclass
class QuickFieldChangeCandidate:
    """A separately owned, validated output awaiting adoption."""

    output_path: Path
    workdir: Path
    changed_count: int
    skipped_count: int


@dataclass
class _RunOutcome:
    result: sandbox.SandboxResult | None = None
    diff_summary: task_diff.TaskDiffSummary | None = None
    error: str | None = None
    changed_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    fields_affected: int = 0
    subfields_affected: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)


def _canonical_request_json(request: QuickFieldChangeRequest) -> str:
    """Return the bounded, deterministic request identity used by Preview."""
    return canonical_request_json(request)


def _bounded_error(value: object) -> str:
    """Keep diagnostics safe to display and safe to retain in session state."""

    text = str(value).replace("\x00", "")[:_MAX_ERROR_CHARS]
    return text.encode("utf-8", "replace")[:_MAX_ERROR_BYTES].decode(
        "utf-8", "ignore"
    )


def _report_progress(
    progress: Callable[..., object] | None,
    processed: int,
    total: int,
) -> None:
    """Bridge sandbox's one-argument callback to the Tasks-page callback.

    Existing Quick runners use ``(processed, total)`` while lower-level
    sandbox callers use ``(processed)``.  Supporting both keeps this runner
    usable by either caller without making progress state part of the model.
    """

    if progress is None:
        return
    try:
        progress(processed, total)
    except TypeError:
        # A one-argument callback is also a valid low-level callback.  The
        # callback is user/UI code; its own TypeError will be surfaced on the
        # second invocation rather than swallowed as a sandbox failure.
        progress(processed)


def _sandbox_error(result: sandbox.SandboxResult) -> str | None:
    """Translate bounded sandbox status/diagnostics to one UI-safe message."""

    if result.cancelled:
        return "Sandbox run was cancelled."
    if result.timed_out:
        return "Sandbox exceeded the maximum processing time."
    if result.error_count:
        first = result.errors[0] if result.errors else {}
        message = first.get("message", "child adapter error")
        if result.error_count > 1:
            message = f"{message} ({result.error_count} errors)"
        return _bounded_error(f"Sandbox reported an adapter error: {message}")
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        suffix = f": {detail[:400]}" if detail else ""
        return _bounded_error(
            f"Sandbox exited with code {result.returncode}{suffix}"
        )
    return None


def _totals_error(result: sandbox.SandboxResult, expected: int) -> str | None:
    """Validate the fixed adapter aggregate emitted by the child."""

    totals = result.adapter_totals
    if not isinstance(totals, dict):
        return "Sandbox did not return structured adapter totals."
    values: dict[str, int] = {}
    for key in _REQUIRED_TOTAL_KEYS:
        value = totals.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            return f"Sandbox returned an invalid adapter total for {key}."
        values[key] = value
    record_total = (
        values["changed_records"]
        + values["unchanged_records"]
        + values["skipped_records"]
    )
    if record_total != expected:
        return (
            f"Sandbox adapter processed {record_total} records for "
            f"{expected} inputs."
        )
    return None


def _run_adapter(
    store,
    request: QuickFieldChangeRequest,
    workdir: Path,
    *,
    progress: Callable[..., object] | None,
) -> _RunOutcome:
    """Stream, sandbox-run, and validate one complete adapter execution."""

    input_path = workdir / "input.mrc"
    store.write_mrc_to(input_path)
    expected = store.count()
    spec = sandbox.TaskSpec(
        name="quick-field-change",
        body="",
        adapter="quick-field-change",
        adapter_payload=request_to_payload(request),
    )
    result = sandbox.run_tasks_subprocess(
        [spec],
        input_path=input_path,
        tmp_dir=workdir,
        progress_path=workdir / "progress.json",
        progress_callback=(
            lambda processed: _report_progress(progress, processed, expected)
            if progress is not None
            else None
        ),
    )
    error = _sandbox_error(result)
    if error is not None:
        return _RunOutcome(result=result, error=error)

    totals_error = _totals_error(result, expected)
    if totals_error is not None:
        return _RunOutcome(result=result, error=totals_error)

    try:
        summary = task_diff.compute_task_diff(input_path, result.output_path)
    except Exception as exc:  # noqa: BLE001 - surfaced as preview error
        return _RunOutcome(
            result=result,
            error=_bounded_error(f"Could not parse sandbox output: {exc}"),
        )

    if summary.total_in != expected or summary.total_out != expected:
        return _RunOutcome(
            result=result,
            diff_summary=summary,
            error=(
                f"Sandbox returned {summary.total_out} records for "
                f"{expected} inputs — refusing a mismatched batch."
            ),
        )

    totals = result.adapter_totals
    changed = int(totals["changed_records"])
    unchanged = int(totals["unchanged_records"])
    skipped = int(totals["skipped_records"])
    # A skipped mutation is an unchanged MARC record, but remains a separate
    # cataloger-facing bucket in the adapter totals.
    if (
        summary.changed_count != changed
        or summary.unchanged_count != unchanged + skipped
    ):
        return _RunOutcome(
            result=result,
            diff_summary=summary,
            error="Sandbox adapter totals did not match its output diff.",
        )
    reasons = totals.get("reason_codes", {})
    if not isinstance(reasons, dict):
        reasons = {}
    reason_counts = {
        str(reason): int(count)
        for reason, count in list(reasons.items())[: sandbox.MAX_ADAPTER_REASON_CODES]
        if isinstance(reason, str)
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
    }
    return _RunOutcome(
        result=result,
        diff_summary=summary,
        changed_count=changed,
        unchanged_count=unchanged,
        skipped_count=skipped,
        fields_affected=int(totals["fields_affected"]),
        subfields_affected=int(totals["subfields_affected"]),
        reason_counts=reason_counts,
    )


def _new_workdir() -> Path:
    workdir = Path(tempfile.mkdtemp(prefix=_ARTIFACT_PREFIX)).resolve()
    token = secrets.token_hex(32)
    marker = {
        "kind": _OWNERSHIP_KIND,
        "token": token,
        "workdir": str(workdir),
    }
    try:
        (workdir / _OWNERSHIP_MARKER).write_text(
            json.dumps(marker, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    _OWNED_ARTIFACTS[workdir] = token
    return workdir


def _artifact_owned(workdir: Path) -> bool:
    """Return whether ``workdir`` is a live artifact created by this runner."""

    try:
        if workdir.is_symlink():
            return False
        resolved = workdir.resolve(strict=True)
        if not resolved.is_dir() or not resolved.name.startswith(_ARTIFACT_PREFIX):
            return False
        expected_token = _OWNED_ARTIFACTS.get(resolved)
        if expected_token is None:
            return False
        marker_path = resolved / _OWNERSHIP_MARKER
        if marker_path.is_symlink() or not marker_path.is_file():
            return False
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        return (
            isinstance(marker, dict)
            and marker.get("kind") == _OWNERSHIP_KIND
            and marker.get("workdir") == str(resolved)
            and isinstance(marker.get("token"), str)
            and secrets.compare_digest(marker["token"], expected_token)
        )
    except (OSError, UnicodeError, TypeError, ValueError):
        return False


def artifact_is_owned(artifact: object | None) -> bool:
    """Return whether a preview/candidate workspace belongs to this runner."""

    if artifact is None:
        return False
    workdir = getattr(
        artifact,
        "workdir",
        artifact if isinstance(artifact, Path) else None,
    )
    if workdir is None:
        return False
    return _artifact_owned(Path(workdir))


def _preview_base(
    request: QuickFieldChangeRequest,
    request_json: str,
    store,
    *,
    job_file_id: int | None,
    job_file_version_id: int | None,
    workdir: Path | None = None,
) -> QuickFieldChangePreview:
    return QuickFieldChangePreview(
        request=request,
        request_json=request_json,
        store_id=id(store),
        store_revision=store.revision,
        job_file_id=job_file_id,
        job_file_version_id=job_file_version_id,
        workdir=workdir,
    )


def build_preview(
    store,
    request: QuickFieldChangeRequest,
    *,
    job_file_id: int | None = None,
    job_file_version_id: int | None = None,
    progress: Callable[..., object] | None = None,
) -> QuickFieldChangePreview:
    """Build a non-mutating, sandbox-backed preview for the full store."""

    try:
        request_json = _canonical_request_json(request)
    except Exception as exc:  # noqa: BLE001 - preview is an error state
        return QuickFieldChangePreview(
            request=request,
            request_json="",
            job_file_id=job_file_id,
            job_file_version_id=job_file_version_id,
            error=_bounded_error(f"Invalid Quick field change request: {exc}"),
        )

    workdir = _new_workdir()
    preview = _preview_base(
        request,
        request_json,
        store,
        job_file_id=job_file_id,
        job_file_version_id=job_file_version_id,
        workdir=workdir,
    )
    try:
        outcome = _run_adapter(store, request, workdir, progress=progress)
    except Exception as exc:  # noqa: BLE001 - keep preview error-state
        cleanup_artifact(workdir)
        preview.workdir = None
        preview.error = _bounded_error(f"Could not run sandbox adapter: {exc}")
        return preview

    preview.output_path = outcome.result.output_path if outcome.result else None
    preview.error = outcome.error
    if outcome.error is not None:
        return preview
    preview.record_count = store.count()
    preview.changed_count = outcome.changed_count
    preview.unchanged_count = outcome.unchanged_count
    preview.skipped_count = outcome.skipped_count
    preview.fields_affected = outcome.fields_affected
    preview.subfields_affected = outcome.subfields_affected
    preview.reason_counts = outcome.reason_counts
    preview.diff_summary = outcome.diff_summary
    return preview


def _assert_preview_current(
    store,
    preview: QuickFieldChangePreview,
    request: QuickFieldChangeRequest,
    *,
    job_file_id: int | None,
    job_file_version_id: int | None,
) -> str:
    """Check all independent identity/version values before Apply reruns."""

    current_json = _canonical_request_json(request)
    if current_json != preview.request_json:
        raise ValueError("Quick field change request changed since preview.")
    if preview.error:
        raise ValueError(f"Preview is in error state: {preview.error}")
    if not artifact_is_owned(preview):
        raise ValueError("Preview artifact is not owned by Quick field changes.")
    if store.count() != preview.record_count:
        raise ValueError("Loaded batch record count changed since preview.")
    if preview.store_id != id(store) or preview.store_revision != store.revision:
        raise ValueError("Loaded batch changed since preview.")
    if (
        preview.job_file_id != job_file_id
        or preview.job_file_version_id != job_file_version_id
    ):
        raise ValueError("Loaded file changed since preview.")
    if preview.output_path is None or not preview.output_path.is_file():
        raise ValueError("Preview output is no longer available.")
    return current_json


def build_apply_candidate(
    store,
    preview: QuickFieldChangePreview,
    request: QuickFieldChangeRequest,
    *,
    job_file_id: int | None = None,
    job_file_version_id: int | None = None,
    progress: Callable[..., object] | None = None,
) -> QuickFieldChangeCandidate:
    """Rerun a current request and return an independently owned candidate.

    Validation failures are raised before the store is touched.  Sandbox or
    aggregate failures also raise and clean only the candidate workspace;
    callers can therefore safely leave the loaded store in place.
    """

    _assert_preview_current(
        store,
        preview,
        request,
        job_file_id=job_file_id,
        job_file_version_id=job_file_version_id,
    )
    workdir = _new_workdir()
    try:
        outcome = _run_adapter(store, request, workdir, progress=progress)
        if outcome.error is not None:
            raise ValueError(outcome.error)
        if outcome.result is None or not outcome.result.output_path.is_file():
            raise ValueError("Sandbox did not produce an output candidate.")
        if (
            outcome.changed_count != preview.changed_count
            or outcome.unchanged_count != preview.unchanged_count
            or outcome.skipped_count != preview.skipped_count
            or outcome.fields_affected != preview.fields_affected
            or outcome.subfields_affected != preview.subfields_affected
        ):
            raise ValueError("Apply output counts differ from the preview.")
        return QuickFieldChangeCandidate(
            output_path=outcome.result.output_path,
            workdir=workdir,
            changed_count=outcome.changed_count,
            skipped_count=outcome.skipped_count,
        )
    except Exception:
        cleanup_artifact(workdir)
        raise


def _owned_output(candidate: QuickFieldChangeCandidate) -> Path:
    workdir = Path(candidate.workdir)
    output = Path(candidate.output_path)
    if not _artifact_owned(workdir):
        raise ValueError("Candidate workspace is not owned by Quick field changes.")
    try:
        resolved_workdir = workdir.resolve(strict=True)
        if output.resolve().parent != resolved_workdir:
            raise ValueError("Candidate output is outside its workspace.")
    except OSError as exc:
        raise ValueError("Candidate output could not be resolved.") from exc
    if not output.is_file():
        raise ValueError("Candidate output is no longer available.")
    return output


def adopt_candidate_to_store(store, candidate: QuickFieldChangeCandidate) -> int:
    """Atomically adopt a validated candidate into ``store``."""

    output = _owned_output(candidate)
    return store.replace_from_path(output)


def cleanup_artifact(artifact: object | None) -> None:
    """Remove only a runner-owned preview/candidate workspace.

    A basename prefix is only a naming convention, not ownership.  The
    marker and in-process token are both required before recursive removal.
    """

    if artifact is None:
        return
    workdir = getattr(artifact, "workdir", artifact if isinstance(artifact, Path) else None)
    if workdir is None:
        return
    path = Path(workdir)
    if not _artifact_owned(path):
        return
    resolved = path.resolve()
    try:
        shutil.rmtree(resolved, ignore_errors=True)
    finally:
        _OWNED_ARTIFACTS.pop(resolved, None)


__all__ = [
    "QuickFieldChangePreview",
    "QuickFieldChangeCandidate",
    "build_preview",
    "build_apply_candidate",
    "cleanup_artifact",
    "artifact_is_owned",
    "adopt_candidate_to_store",
]
