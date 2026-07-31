"""Sandboxed one-record previews for guided find-and-replace operations."""

from __future__ import annotations

import copy
import io
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import pymarc

from marcedit_web.lib import (
    guided_replace,
    guided_replace_validation,
    sandbox,
    task_authoring,
    task_builder,
)


_MAX_ERROR_CHARS = 1024
_MAX_ERROR_BYTES = 2048
_MAX_DISPLAY_BYTES = sandbox.MAX_STDERR_BYTES


@dataclass(frozen=True)
class GuidedReplacePreview:
    request: dict
    store_id: Optional[int]
    store_revision: Optional[int]
    before: str = ""
    after: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None


def _normalized(operation: Mapping[str, Any]) -> dict:
    normalized = task_authoring.normalize_operation(operation)
    errors = task_authoring.validate_operation(
        normalized,
        validate_raw_syntax=False,
    )
    if errors:
        raise ValueError("; ".join(errors))
    return normalized


def preview_cache_key(operation: Mapping[str, Any]) -> str:
    """Return canonical normalized request JSON for the session cache."""

    normalized = _normalized(operation)
    return guided_replace_validation.canonical_request_json(
        normalized["params"]
    )


def is_current(
    preview: GuidedReplacePreview,
    store,
    operation: Mapping[str, Any],
) -> bool:
    """Report whether a successful preview still describes this request."""

    try:
        normalized = _normalized(operation)
    except (TypeError, ValueError):
        return False
    return (
        preview.error is None
        and preview.store_id == id(store)
        and preview.store_revision == getattr(store, "revision", None)
        and preview.request == normalized["params"]
    )


def build_preview(
    store,
    operation: Mapping[str, Any],
) -> GuidedReplacePreview:
    """Run one normalized operation against only the first store record."""

    store_id = id(store)
    store_revision = getattr(store, "revision", None)
    try:
        normalized = _normalized(operation)
    except (TypeError, ValueError) as exc:
        return GuidedReplacePreview(
            request={},
            store_id=store_id,
            store_revision=store_revision,
            error=_bounded_error("Preview validation failed: {0}".format(exc)),
        )

    if store.count() == 0:
        return GuidedReplacePreview(
            request=normalized["params"],
            store_id=store_id,
            store_revision=store_revision,
            error="No loaded record is available to preview.",
        )

    source_record = store.get(0)
    if source_record is None:
        return GuidedReplacePreview(
            request=normalized["params"],
            store_id=store_id,
            store_revision=store_revision,
            error="No loaded record is available to preview.",
        )
    source_record = copy.deepcopy(source_record)

    before = _format_selected_values(source_record, normalized["params"])
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-guided-preview-"))
    try:
        rendered = task_builder.render_ops_to_python([
            task_builder.Operation.from_dict(normalized)
        ])
        body = (
            "_guided_replace_result = {"
            "'matched_values': 0, "
            "'changed_values': 0, "
            "'matched_occurrences': 0}\n"
            + rendered["body"]
        )
        result = sandbox.run_tasks_subprocess(
            [
                sandbox.TaskSpec(
                    name="guided-find-replace-preview",
                    body=body,
                    imports=rendered["imports"],
                    capture_result="_guided_replace_result",
                )
            ],
            record_bytes=_record_bytes(source_record),
            tmp_dir=workdir,
        )
        error = _sandbox_error(result)
        if error is not None:
            return GuidedReplacePreview(
                request=normalized["params"],
                store_id=store_id,
                store_revision=store_revision,
                before=before,
                error=error,
            )

        output_records = _read_records(result.output_path)
        if len(output_records) != 1:
            raise ValueError("sandbox returned an unexpected record count")
        if len(result.captured_results) != 1:
            raise ValueError("sandbox returned an unexpected preview result")
        captured = result.captured_results[0].get("result")
        if not _valid_counts(captured):
            raise ValueError("sandbox returned invalid preview counts")
        return GuidedReplacePreview(
            request=normalized["params"],
            store_id=store_id,
            store_revision=store_revision,
            before=before,
            after=_format_selected_values(
                output_records[0], normalized["params"]
            ),
            result=dict(captured),
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return GuidedReplacePreview(
            request=normalized["params"],
            store_id=store_id,
            store_revision=store_revision,
            before=before,
            error=_bounded_error("Preview failed: {0}".format(exc)),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _record_bytes(record) -> bytes:
    stream = io.BytesIO()
    writer = pymarc.MARCWriter(stream)
    writer.write(record)
    return stream.getvalue()


def _read_records(path: Path) -> list:
    with path.open("rb") as source:
        return [
            record
            for record in pymarc.MARCReader(
                source, to_unicode=True, permissive=True
            )
            if record is not None
        ]


def _format_selected_values(record, params: Mapping[str, Any]) -> str:
    lines = []
    for field, subfield_index, value in guided_replace._selected_values(
        record,
        str(params["target_kind"]),
        str(params["tag"]),
        str(params["subfield"]),
    ):
        if subfield_index is None:
            lines.append("{0} {1}".format(field.tag, value))
        else:
            code = field.subfields[subfield_index].code
            lines.append("{0} ${1}{2}".format(field.tag, code, value))
    return _bounded_display("\n".join(lines), selected_values=len(lines))


def _bounded_display(value: str, *, selected_values: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= _MAX_DISPLAY_BYTES:
        return value
    marker = (
        "\n...[preview truncated: {0} bytes across {1} selected values; "
        "limit {2} bytes]...\n"
    ).format(len(encoded), selected_values, _MAX_DISPLAY_BYTES)
    marker_bytes = marker.encode("utf-8")
    remaining = _MAX_DISPLAY_BYTES - len(marker_bytes)
    head_size = remaining // 2
    tail_size = remaining - head_size
    return (
        encoded[:head_size].decode("utf-8", "ignore")
        + marker
        + encoded[-tail_size:].decode("utf-8", "ignore")
    )


def _sandbox_error(result: sandbox.SandboxResult) -> Optional[str]:
    if result.timed_out:
        return "Preview timed out in the sandbox."
    if result.cancelled:
        return "Preview was cancelled in the sandbox."
    if result.returncode != 0:
        return _bounded_error(
            "Preview sandbox exited with code {0}: {1}".format(
                result.returncode, result.stderr.strip()
            )
        )
    if result.error_count or result.errors:
        message = (
            result.errors[0].get("message", "sandbox transform failed")
            if result.errors
            else "sandbox transform failed"
        )
        return _bounded_error("Preview failed: {0}".format(message))
    return None


def _valid_counts(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return set(value) == {
        "matched_values",
        "changed_values",
        "matched_occurrences",
    } and all(
        isinstance(value[name], int) and value[name] >= 0
        for name in value
    )


def _bounded_error(message: object) -> str:
    text = str(message).replace("\x00", "")[:_MAX_ERROR_CHARS]
    return text.encode("utf-8", "replace")[:_MAX_ERROR_BYTES].decode(
        "utf-8", "ignore"
    )
