"""Bounded subprocess validation for guided raw regular expressions."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

import pymarc

from marcedit_web.lib import sandbox


MAX_REQUEST_CHARS = sandbox.MAX_ERROR_MESSAGE_CHARS
MAX_REQUEST_BYTES = sandbox.MAX_ERROR_MESSAGE_BYTES


def canonical_request_json(params: Mapping[str, Any]) -> str:
    """Return exact canonical JSON or reject state that cannot be retained."""

    try:
        request_json = json.dumps(
            params,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError, MemoryError) as exc:
        raise ValueError(
            _bounded_error(
                "Guided replacement request is not safely serializable: "
                "{0}: {1}".format(type(exc).__name__, exc)
            )
        ) from exc
    if (
        len(request_json) > MAX_REQUEST_CHARS
        or len(request_json.encode("utf-8")) > MAX_REQUEST_BYTES
    ):
        raise ValueError(
            "Guided replacement request exceeds the "
            "{0}-character/{1}-byte limit.".format(
                MAX_REQUEST_CHARS,
                MAX_REQUEST_BYTES,
            )
        )
    return request_json


def request_size_error(params: Mapping[str, Any]) -> Optional[str]:
    """Return a bounded request-retention error, if any."""

    try:
        canonical_request_json(params)
    except ValueError as exc:
        return _bounded_error(str(exc))
    return None


def validate_raw_regex(
    *,
    find: str,
    replacement: str,
    ignore_case: bool,
) -> tuple[str, ...]:
    """Validate raw pattern syntax and capture references in the sandbox."""

    size_error = request_size_error({
        "find": find,
        "replacement": replacement,
        "ignore_case": ignore_case,
    })
    if size_error is not None:
        return (size_error,)
    try:
        workdir = Path(
            tempfile.mkdtemp(prefix="marcedit-guided-regex-validation-")
        )
    except (OSError, MemoryError, RecursionError) as exc:
        return (_launcher_error(exc),)
    try:
        flags = "re.IGNORECASE" if ignore_case else "0"
        body = (
            "_guided_raw_pattern = re.compile({0}, {1})\n"
            "_guided_raw_pattern.sub({2}, '')"
        ).format(repr(find), flags, repr(replacement))
        try:
            result = sandbox.run_tasks_subprocess(
                [
                    sandbox.TaskSpec(
                        name="guided-raw-regex-validation",
                        body=body,
                        imports=["import re"],
                    )
                ],
                record_bytes=_synthetic_record_bytes(),
                timeout=sandbox.DEFAULT_PROCESSING_LIMIT_SECONDS,
                tmp_dir=workdir,
            )
        except (
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            MemoryError,
            RecursionError,
        ) as exc:
            return (_launcher_error(exc),)
        if result.timed_out:
            return (
                "Regular expression validation timed out in the sandbox.",
            )
        if result.cancelled:
            return (
                "Regular expression validation was cancelled in the sandbox.",
            )
        if result.returncode != 0:
            return (
                _bounded_error(
                    "Regular expression validation sandbox exited with "
                    "code {0}: {1}".format(
                        result.returncode,
                        result.stderr.strip(),
                    )
                ),
            )
        if result.error_count or result.errors:
            message = (
                result.errors[0].get(
                    "message", "sandbox validation failed"
                )
                if result.errors
                else "sandbox validation failed"
            )
            return (
                _bounded_error(
                    "Regular expression validation failed: {0}".format(
                        message
                    )
                ),
            )
        return ()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _synthetic_record_bytes() -> bytes:
    stream = io.BytesIO()
    writer = pymarc.MARCWriter(stream)
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag="001", data="REGEX-VALIDATION"))
    writer.write(record)
    return stream.getvalue()


def _launcher_error(exc: BaseException) -> str:
    return _bounded_error(
        "Regular expression validation could not start: {0}: {1}".format(
            type(exc).__name__,
            exc,
        )
    )


def _bounded_error(message: object) -> str:
    text = str(message).replace("\x00", "")[
        :sandbox.MAX_ERROR_MESSAGE_CHARS
    ]
    return text.encode("utf-8", "replace")[
        :sandbox.MAX_ERROR_MESSAGE_BYTES
    ].decode("utf-8", "ignore")
