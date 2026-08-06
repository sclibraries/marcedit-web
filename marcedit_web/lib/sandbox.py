"""Subprocess sandbox for user task execution.

User-authored task bodies — admin Code view, form-builder rendered
Python, MarcEdit-imported converters — are arbitrary Python that
mutates a ``pymarc.Record``. The v2 design ran them directly inside
the Streamlit process; v3 routes them through a child Python that has

* CPU limit (``RLIMIT_CPU``)
* Address-space limit (``RLIMIT_AS``)
* File-size limit (``RLIMIT_FSIZE``)
* Process-count limit (``RLIMIT_NPROC``)
* Wall-clock timeout enforced by the parent (``subprocess.communicate(timeout=...)``)
* Empty environment except for ``PYTHONPATH`` (so ``marcedit_web.lib``
  imports resolve) and ``PATH`` (so ``python3`` can locate its own
  modules)
* Working directory pinned to a fresh temp dir

This is **not** a full sandbox — a determined attacker who clears the
rlimits or escapes via a CPython bug can still cause damage. The goal
is to bound the blast radius of accidental or buggy user task code
to "this one execution can't take down the Streamlit server."

What it does NOT enforce:

* No restricted import / blocked-modules policy. ``subprocess``,
  ``socket``, ``os.system``, ``ctypes``, etc. all load normally in
  the child. A task body that calls ``subprocess.run(["/bin/sh",
  "-c", "true"])`` succeeds.
* No filesystem chroot. The child can read or write any path the
  ``marcedit`` container user can — TASK-029 / Stage Medium 1
  tightened that to ``/app/data`` only, but ``/etc``, ``/tmp``,
  etc. remain reachable.
* No network namespace. Outbound TCP works unless the deployment's
  network policy blocks it.

Stage 21 added the non-root container user. Future hardening
(seccomp, network namespace, restricted-Python policy) would
strengthen the boundary further but is out of scope today.
"""

from __future__ import annotations

import json
import logging
import math
import os
import resource
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable, Iterable, Optional

from marcedit_web.lib import task_preflight

logger = logging.getLogger("marcedit_web.sandbox")

_ADAPTER_ALLOWLIST = frozenset({"quick-field-change"})


# Bytes-per-resource ceilings. Tuned for "100K records of small/medium
# pymarc.Record objects fits in 512 MB" — there's some headroom for
# pymarc + marcedit_web import overhead.
DEFAULT_PROCESSING_LIMIT_SECONDS = 300
_AS_BYTES = 512 * 1024 * 1024     # 512 MB virtual memory
_FSIZE_BYTES = 1024 * 1024 * 1024  # 1 GB single-file write cap
_NPROC = 32                        # subprocess can't fork-bomb
MAX_RETAINED_ERRORS = 200
MAX_ERROR_CODE_CHARS = 64
MAX_ERROR_CODE_BYTES = 128
MAX_ERROR_TASK_CHARS = 128
MAX_ERROR_TASK_BYTES = 256
MAX_ERROR_MESSAGE_CHARS = 1024
MAX_ERROR_MESSAGE_BYTES = 2048
MAX_ERROR_DETAIL_BYTES = 4096
MAX_ERROR_PAYLOAD_BYTES = MAX_RETAINED_ERRORS * MAX_ERROR_DETAIL_BYTES
MAX_STDERR_BYTES = 8192
MAX_ADAPTER_PAYLOAD_CHARS = 65_536
MAX_ADAPTER_PAYLOAD_BYTES = 131_072
MAX_ADAPTER_REASON_CODES = 20
_TERMINATION_GRACE_SECONDS = 2


@dataclass
class TaskSpec:
    """One task to run, in order, against every record."""

    name: str
    body: str
    imports: list[str] = field(default_factory=list)
    capture_result: Optional[str] = None
    partner_batch_limits: dict[str, int] = field(default_factory=dict)
    adapter: Optional[str] = None
    adapter_payload: object = None


@dataclass
class SandboxResult:
    """Outcome of a single sandbox invocation.

    ``output_path`` is the MARC file the child produced (possibly empty
    when the run failed before any record was written). Keeping it on disk
    prevents the Streamlit process from duplicating a large batch in RAM.
    ``error_count`` is exact while ``errors`` retains only the first capped
    diagnostics. ``stderr`` is the raw child stderr — surfaced for debugging
    when the run failed outside the per-record loop (import error, segfault,
    etc). ``timed_out`` is True when a processing-time cap fired;
    ``cancelled`` is independently True for a user-requested stop.
    """

    output_path: Path
    errors: list[dict]
    error_count: int = 0
    stderr: str = ""
    returncode: int = 0
    timed_out: bool = False
    cancelled: bool = False
    captured_results: list[dict] = field(default_factory=list)
    partner_totals: dict[str, int] = field(default_factory=dict)
    adapter_totals: dict[str, object] = field(default_factory=dict)


# Inlined driver script — passed via -c to the child. Kept here so the
# sandbox is self-contained (no separate file to ship + path issues
# inside the container).
_DRIVER_SCRIPT = r"""
import argparse
import copy
import io
import json
import os
import resource
import sys
import traceback

def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--progress")
    ap.add_argument("--max-errors", required=True, type=int)
    ap.add_argument("--max-code-chars", required=True, type=int)
    ap.add_argument("--max-code-bytes", required=True, type=int)
    ap.add_argument("--max-task-chars", required=True, type=int)
    ap.add_argument("--max-task-bytes", required=True, type=int)
    ap.add_argument("--max-message-chars", required=True, type=int)
    ap.add_argument("--max-message-bytes", required=True, type=int)
    ap.add_argument("--cpu-seconds", required=True, type=int)
    return ap.parse_args()


def _write_progress(path, processed_records):
    if not path:
        return
    temporary = path + ".tmp"
    with open(temporary, "w") as progress_file:
        json.dump({"processed_records": processed_records}, progress_file)
    os.replace(temporary, path)


def _bounded_text(value, max_chars, max_bytes):
    text = str(value).replace("\x00", "")[:max_chars]
    return text.encode("utf-8", "replace")[:max_bytes].decode(
        "utf-8", "ignore"
    )


def _validated_capture_result(value):
    keys = {
        "matched_values",
        "changed_values",
        "matched_occurrences",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("captured result is not a guided count result")
    for key in keys:
        count = value[key]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            or count > 2147483647
        ):
            raise ValueError("captured guided count is out of bounds")
    return {key: value[key] for key in sorted(keys)}


# Defensive re-set of rlimits inside the child. The parent's preexec_fn
# also sets these; we duplicate here so the limits are visible if
# someone bypasses preexec.
def _set_limits(cpu_seconds):
    try:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (cpu_seconds, cpu_seconds + 1),
        )
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,
                                                 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024 * 1024,
                                                    1024 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except (ValueError, resource.error):
        # Already at the limit or unsupported; not fatal.
        pass

args = _parse_args()
_set_limits(args.cpu_seconds)

import pymarc
from marcedit_web.lib import transforms  # standard helpers in scope
from marcedit_web.lib import quick_field_changes


# Structured adapters are intentionally dispatched through this literal map.
# Do not derive a callable from request data with globals(), getattr(), or a
# module path: the request may select only the fixed adapter named here.
_ADAPTER_PREPARERS = {
    "quick-field-change": quick_field_changes.prepare_quick_field_change_adapter,
}


_ADAPTER_RESULT_KEYS = {
    "changed",
    "skipped",
    "reason",
    "fields_affected",
    "subfields_affected",
}


def _new_adapter_totals():
    return {
        "changed_records": 0,
        "unchanged_records": 0,
        "skipped_records": 0,
        "fields_affected": 0,
        "subfields_affected": 0,
        "reason_codes": {},
    }


def _record_adapter_result(totals, result):
    if not isinstance(result, dict) or set(result) != _ADAPTER_RESULT_KEYS:
        raise ValueError("structured adapter returned an invalid result")
    changed = result["changed"]
    skipped = result["skipped"]
    reason = result["reason"]
    fields_affected = result["fields_affected"]
    subfields_affected = result["subfields_affected"]
    if not isinstance(changed, bool) or not isinstance(skipped, bool):
        raise ValueError("structured adapter result flags are invalid")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("structured adapter result reason is invalid")
    for value in (fields_affected, subfields_affected):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > 2147483647
        ):
            raise ValueError("structured adapter result counts are invalid")
    if skipped:
        totals["skipped_records"] += 1
    elif changed:
        totals["changed_records"] += 1
    else:
        totals["unchanged_records"] += 1
    totals["fields_affected"] += fields_affected
    totals["subfields_affected"] += subfields_affected
    if reason:
        reason = reason.replace("\x00", "")[:64]
        reason = reason.encode("utf-8", "replace")[:128].decode(
            "utf-8", "ignore"
        )
        reasons = totals["reason_codes"]
        if reason in reasons:
            reasons[reason] += 1
        elif len(reasons) < 20:
            reasons[reason] = 1


def _validate_adapter_payload_size(payload):
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("adapter payload must be JSON-serializable") from exc
    if len(encoded) > 65536:
        raise ValueError("adapter payload exceeds the maximum character size")
    if len(encoded.encode("utf-8")) > 131072:
        raise ValueError("adapter payload exceeds the maximum byte size")


def _prepare_tasks(tasks):
    prepared_adapters = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("sandbox task must be an object")
        body = task.get("body", "")
        adapter = task.get("adapter")
        payload = task.get("adapter_payload")
        if adapter is not None:
            if body != "":
                raise ValueError("task body and adapter are mutually exclusive")
            if not isinstance(adapter, str) or adapter not in _ADAPTER_PREPARERS:
                raise ValueError("structured adapter is not allowlisted")
            _validate_adapter_payload_size(payload)
            prepared_adapters.append(
                _ADAPTER_PREPARERS[adapter](payload)
            )
        else:
            if payload is not None:
                raise ValueError("adapter payload requires an adapter")
            prepared_adapters.append(None)
    return prepared_adapters


def main():
    with open(args.tasks) as f:
        tasks = json.load(f)

    prepared_adapters = _prepare_tasks(tasks)

    errors = []
    error_count = 0
    captured_results = []
    partner_totals = {}
    adapter_totals = (
        _new_adapter_totals()
        if any(adapter is not None for adapter in prepared_adapters)
        else {}
    )
    transforms.reset_partner_batch_totals()
    with open(args.input, "rb") as fin:
        reader = pymarc.MARCReader(fin, to_unicode=True, permissive=True)
        with open(args.output, "wb") as fout:
            writer = pymarc.MARCWriter(fout)
            for idx, record in enumerate(reader, start=1):
                if record is None:
                    error_count += 1
                    if len(errors) < args.max_errors:
                        errors.append({
                            "index": idx,
                            "code": "malformed-record",
                            "task": None,
                            "message": "pymarc skipped a malformed record",
                        })
                    _write_progress(args.progress, idx)
                    continue
                failed_task = None
                original_record = (
                    copy.deepcopy(record)
                    if any(adapter is not None for adapter in prepared_adapters)
                    else None
                )
                try:
                    for task_index, task in enumerate(tasks):
                        # Fresh namespace per task so symbols don't leak.
                        transforms.set_partner_batch_context(str(task_index))
                        ns = {
                            "record": record,
                            "pymarc": pymarc,
                            "Field": pymarc.Field,
                            "Subfield": pymarc.Subfield,
                            "transforms": transforms,
                        }
                        # Pre-expose every public transforms helper at
                        # the top level so form-builder-generated
                        # bodies (e.g. `delete_tags(record, "029")`)
                        # resolve. The parent strips module-level
                        # imports when parsing the task file body, so
                        # this preload is the contract.
                        for _name in dir(transforms):
                            if not _name.startswith("_"):
                                ns[_name] = getattr(transforms, _name)
                        if prepared_adapters[task_index] is not None:
                            adapter_result = prepared_adapters[task_index](record)
                            _record_adapter_result(adapter_totals, adapter_result)
                        else:
                            # Imports requested by the task (e.g. specific
                            # transforms helpers) — run first.
                            for imp in task.get("imports", []):
                                exec(compile(imp, "<task-import>", "exec"), ns)
                            exec(compile(
                                task["body"],
                                "<task:%s>" % task.get("name", "?"),
                                "exec",
                            ), ns)
                            capture_name = task.get("capture_result")
                            if capture_name and len(captured_results) < idx:
                                value = _validated_capture_result(
                                    ns.get(capture_name)
                                )
                                json.dumps(value)
                                captured_results.append({
                                    "record_index": idx,
                                    "task": _bounded_text(
                                        task.get("name", "?"),
                                        args.max_task_chars,
                                        args.max_task_bytes,
                                    ),
                                    "result": value,
                                })
                    writer.write(record)
                except Exception as exc:
                    if original_record is not None:
                        record = original_record
                    failed_task = task.get("name", "?") if 'task' in locals() else "?"
                    error_count += 1
                    if len(errors) < args.max_errors:
                        errors.append({
                            "index": idx,
                            "code": "transform-failed",
                            "task": _bounded_text(
                                failed_task,
                                args.max_task_chars,
                                args.max_task_bytes,
                            ),
                            "message": _bounded_text(
                                "%s: %s" % (type(exc).__name__, exc),
                                args.max_message_chars,
                                args.max_message_bytes,
                            ),
                        })
                    # Keep original record so the output batch stays the
                    # same cardinality as the input.
                    writer.write(record)
                _write_progress(args.progress, idx)

    with open(args.errors, "w") as f:
        json.dump({
            "error_count": error_count,
            "errors": errors,
            "captured_results": captured_results,
            "partner_totals": transforms.get_partner_batch_totals(),
            "adapter_totals": adapter_totals,
        }, f)


if __name__ == "__main__":
    main()
"""


def _cpu_limit_seconds(timeout: float) -> int:
    """Return a positive whole-second CPU budget for an elapsed timeout."""
    return max(1, math.ceil(timeout))


def _preexec_set_limits(cpu_seconds: int) -> None:
    """Apply supported resource limits between fork and exec.

    Some POSIX hosts expose a limit constant but reject setting it (macOS,
    for example, may reject the address-space ceiling). A single unsupported
    limit must not abort ``Popen``'s ``preexec_fn`` and hide the useful
    limits that follow it; the child driver applies the same best-effort
    policy after exec.
    """
    limits = (
        (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1)),
        (resource.RLIMIT_AS, (_AS_BYTES, _AS_BYTES)),
        (resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES)),
        (resource.RLIMIT_NPROC, (_NPROC, _NPROC)),
    )
    for resource_id, value in limits:
        try:
            resource.setrlimit(resource_id, value)
        except (ValueError, resource.error):
            continue


def _resolved_pythonpath(value: str) -> str:
    """Make parent-relative import paths survive the child cwd change."""
    if not value:
        return ""
    base = Path.cwd()
    entries = []
    for entry in value.split(os.pathsep):
        path = Path(entry or ".")
        entries.append(
            str(path if path.is_absolute() else (base / path).resolve())
        )
    return os.pathsep.join(entries)


def _canonical_adapter_payload(payload: object) -> object:
    """Validate, bound, and normalize one structured adapter payload."""
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("adapter payload must be JSON-serializable") from exc
    if len(encoded) > MAX_ADAPTER_PAYLOAD_CHARS:
        raise ValueError(
            "adapter payload exceeds the maximum of "
            f"{MAX_ADAPTER_PAYLOAD_CHARS:,} characters"
        )
    encoded_bytes = encoded.encode("utf-8")
    if len(encoded_bytes) > MAX_ADAPTER_PAYLOAD_BYTES:
        raise ValueError(
            "adapter payload exceeds the maximum of "
            f"{MAX_ADAPTER_PAYLOAD_BYTES:,} bytes"
        )
    # Use the canonical JSON representation as the child request value. This
    # prevents insertion-order differences from changing the serialized task.
    return json.loads(encoded)


def run_tasks_subprocess(
    tasks: Iterable[TaskSpec],
    record_bytes: Optional[bytes] = None,
    *,
    input_path: Optional[Path] = None,
    timeout: float = DEFAULT_PROCESSING_LIMIT_SECONDS,
    tmp_dir: Optional[Path] = None,
    progress_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    poll_interval: float = 0.25,
) -> SandboxResult:
    """Apply ``tasks`` (in order) to every record in the input.

    Two ways to supply the input MARC:

    * ``record_bytes`` — the existing API, fine for unit tests where
      the corpus is small enough to fit in memory.
    * ``input_path`` — a path to a pre-written ``.mrc`` file. The
      Tasks page uses :py:meth:`RecordStore.write_mrc_to` to stream
      records to a temp file, then hands the path here so neither
      side has to hold the full batch in memory.

    Supplying both is a ``ValueError``; supplying neither is the same.

    Spawns a child Python with rlimits, hands it the inputs via temp
    files, captures the MARC output + JSON error log. Never raises on
    user-task errors — those land in ``SandboxResult.errors``. Raises
    ``RuntimeError`` only on launcher-level problems (can't write the
    temp files, can't spawn python at all).
    """
    cpu_seconds = _cpu_limit_seconds(timeout)
    if poll_interval <= 0:
        raise ValueError("poll_interval must be greater than zero")
    if (record_bytes is None) == (input_path is None):
        raise ValueError(
            "exactly one of record_bytes or input_path is required"
        )

    tasks_list = []
    for task_spec in tasks:
        adapter = task_spec.adapter
        body = task_spec.body
        if adapter is not None:
            if body != "":
                raise ValueError(
                    "task body and adapter are mutually exclusive"
                )
            if not isinstance(adapter, str) or adapter not in _ADAPTER_ALLOWLIST:
                raise ValueError("structured adapter is not allowlisted")
            if task_spec.adapter_payload is None:
                payload = None
            else:
                payload = _canonical_adapter_payload(task_spec.adapter_payload)
            # Validate request shape in the parent without preparing or
            # matching fields. Raw regular expressions therefore compile only
            # inside the child adapter boundary.
            if adapter == "quick-field-change":
                from marcedit_web.lib import quick_field_changes

                try:
                    request = quick_field_changes.request_from_payload(payload)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"adapter operation payload is invalid: {exc}") from exc
                request_errors = quick_field_changes.validate_request(request)
                if request_errors:
                    raise ValueError(
                        "adapter operation payload is invalid: "
                        + "; ".join(request_errors)
                    )
        else:
            if task_spec.adapter_payload is not None:
                raise ValueError("adapter payload requires an adapter")
            task_preflight.assert_runnable_task_body(body)
            payload = None
        tasks_list.append({
            "name": task_spec.name,
            "body": body,
            "imports": list(task_spec.imports),
            "capture_result": task_spec.capture_result,
            "partner_batch_limits": dict(task_spec.partner_batch_limits),
            "adapter": adapter,
            "adapter_payload": payload,
        })

    workdir = (
        tmp_dir
        if tmp_dir is not None
        else Path(tempfile.mkdtemp(prefix="marcedit-web-sandbox-"))
    )
    workdir.mkdir(parents=True, exist_ok=True)
    if input_path is None:
        sandbox_input_path = workdir / "input.mrc"
        sandbox_input_path.write_bytes(record_bytes or b"")
    else:
        # Caller has already written the file (typically via
        # RecordStore.write_mrc_to). Use it directly — skipping the
        # write avoids holding the batch bytes in this process.
        sandbox_input_path = input_path

    tasks_path = workdir / "tasks.json"
    output_path = workdir / "output.mrc"
    errors_path = workdir / "errors.json"
    stderr_path = workdir / "stderr.log"
    for result_path in (output_path, errors_path, stderr_path):
        result_path.unlink(missing_ok=True)
    tasks_path.write_text(
        json.dumps(
            tasks_list,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    if progress_path is not None:
        progress_path = progress_path.absolute()
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.unlink(missing_ok=True)
        Path(str(progress_path) + ".tmp").unlink(missing_ok=True)

    cmd = [
        sys.executable,
        "-c",
        _DRIVER_SCRIPT,
        "--input", str(sandbox_input_path),
        "--tasks", str(tasks_path),
        "--output", str(output_path),
        "--errors", str(errors_path),
        "--max-errors", str(MAX_RETAINED_ERRORS),
        "--max-code-chars", str(MAX_ERROR_CODE_CHARS),
        "--max-code-bytes", str(MAX_ERROR_CODE_BYTES),
        "--max-task-chars", str(MAX_ERROR_TASK_CHARS),
        "--max-task-bytes", str(MAX_ERROR_TASK_BYTES),
        "--max-message-chars", str(MAX_ERROR_MESSAGE_CHARS),
        "--max-message-bytes", str(MAX_ERROR_MESSAGE_BYTES),
        "--cpu-seconds", str(cpu_seconds),
    ]
    if progress_path is not None:
        cmd.extend(["--progress", str(progress_path)])
    # Cleansed environment: PYTHONPATH (for marcedit_web imports),
    # PATH (for the python invocation), HOME (some libraries demand
    # one). Nothing else.
    env = {
        "PYTHONPATH": _resolved_pythonpath(os.environ.get("PYTHONPATH", "")),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workdir),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    timed_out = False
    cancelled = False
    stderr = ""
    returncode = 0
    communicated_stderr = None
    stderr_file = stderr_path.open("w", encoding="utf-8")
    try:
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                env=env,
                preexec_fn=partial(_preexec_set_limits, cpu_seconds),
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            # The python interpreter wasn't found — that's a launcher bug.
            raise RuntimeError(
                f"sandbox could not spawn python: {exc}"
            ) from exc

        started_at = time.monotonic()
        last_progress = None
        process_reaped = False
        try:
            while True:
                if process.poll() is not None:
                    _, communicated_stderr = process.communicate()
                    process_reaped = True
                    break

                if cancel_requested is not None and cancel_requested():
                    cancelled = True
                    _, communicated_stderr = _terminate_process_group(process)
                    process_reaped = True
                    break

                last_progress = _report_progress(
                    progress_path,
                    progress_callback,
                    last_progress,
                )

                remaining = timeout - (time.monotonic() - started_at)
                if remaining <= 0:
                    timed_out = True
                    _, communicated_stderr = _terminate_process_group(process)
                    process_reaped = True
                    logger.warning("sandbox timed out after %.1fs", timeout)
                    break

                try:
                    _, communicated_stderr = process.communicate(
                        timeout=min(poll_interval, remaining),
                    )
                    process_reaped = True
                    break
                except subprocess.TimeoutExpired:
                    continue

            if not cancelled:
                _report_progress(
                    progress_path,
                    progress_callback,
                    last_progress,
                )
        except BaseException:
            if not process_reaped:
                _terminate_process_group(process)
            raise
    finally:
        stderr_file.close()

    if communicated_stderr is not None:
        stderr = _bounded_text(
            communicated_stderr,
            MAX_STDERR_BYTES,
            MAX_STDERR_BYTES,
        )
    elif stderr_path.exists():
        stderr = _read_bounded_stderr(stderr_path)
    returncode = process.returncode
    if returncode == -signal.SIGXCPU and not cancelled:
        timed_out = True
        logger.warning(
            "sandbox exceeded CPU processing limit after %.1fs",
            timeout,
        )

    try:
        error_payload = json.loads(
            _read_bounded_file(errors_path, MAX_ERROR_PAYLOAD_BYTES)
        ) if errors_path.exists() else []
    except json.JSONDecodeError:
        error_payload = []

    if isinstance(error_payload, dict):
        errors = [
            bound_error(error)
            for error in list(error_payload.get("errors") or [])[
                :MAX_RETAINED_ERRORS
            ]
            if isinstance(error, dict)
        ]
        error_count = int(error_payload.get("error_count", len(errors)))
        captured_results = [
            captured
            for captured in list(
                error_payload.get("captured_results") or []
            )
            if isinstance(captured, dict)
        ]
        raw_totals = error_payload.get("partner_totals") or {}
        if not isinstance(raw_totals, dict):
            raw_totals = {}
        partner_totals = {
            str(key): int(value)
            for key, value in raw_totals.items()
            if isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 2_147_483_647
        }
        adapter_totals = _bound_adapter_totals(
            error_payload.get("adapter_totals")
        )
    else:
        errors = [
            bound_error(error)
            for error in list(error_payload)[:MAX_RETAINED_ERRORS]
            if isinstance(error, dict)
        ]
        error_count = len(errors)
        captured_results = []
        partner_totals = {}
        adapter_totals = {}

    if timed_out:
        error_count += 1
        _retain_terminal_error(errors, {
            "index": 0,
            "code": "sandbox-timeout",
            "task": None,
            "message": (
                f"sandbox exceeded {timeout:.0f}s maximum processing time"
            ),
        })
    elif returncode != 0 and not cancelled:
        error_count += 1
        _retain_terminal_error(errors, {
            "index": 0,
            "code": "sandbox-nonzero-exit",
            "task": None,
            "message": (
                f"sandbox exited with code {returncode}. stderr: "
                f"{stderr.strip()[:1024]}"
            ),
        })

    return SandboxResult(
        output_path=output_path,
        errors=errors,
        error_count=error_count,
        stderr=stderr,
        returncode=returncode,
        timed_out=timed_out,
        cancelled=cancelled,
        captured_results=captured_results,
        partner_totals=partner_totals,
        adapter_totals=adapter_totals,
    )


def _report_progress(
    progress_path: Optional[Path],
    progress_callback: Optional[Callable[[int], None]],
    last_progress: Optional[int],
) -> Optional[int]:
    """Report a complete, changed progress sidecar value at most once."""
    if progress_path is None or progress_callback is None:
        return last_progress
    try:
        payload = json.loads(progress_path.read_text())
        processed_records = payload["processed_records"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return last_progress
    if (
        not isinstance(processed_records, int)
        or processed_records == last_progress
    ):
        return last_progress
    progress_callback(processed_records)
    return processed_records


def _terminate_process_group(
    process: subprocess.Popen,
) -> tuple[Optional[str], Optional[str]]:
    """Terminate the owned group, then reap its unreused leader PID."""
    if _signal_process_group(process, signal.SIGTERM):
        time.sleep(_TERMINATION_GRACE_SECONDS)
        _signal_process_group(process, signal.SIGKILL)
    return process.communicate()


def _signal_process_group(process: subprocess.Popen, sig: int) -> bool:
    """Signal the owned process group; report whether it still exists."""
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return False
    return True


def _retain_terminal_error(errors: list[dict], error: dict) -> None:
    """Keep a launcher error visible without exceeding the diagnostics cap."""
    error = bound_error(error)
    if len(errors) < MAX_RETAINED_ERRORS:
        errors.append(error)
    elif errors:
        errors[-1] = error


def bound_error(error: dict) -> dict:
    """Return one normalized diagnostic within explicit character/byte caps."""
    try:
        index = max(0, int(error.get("index", 0)))
    except (TypeError, ValueError):
        index = 0
    task = error.get("task")
    return {
        "index": index,
        "code": _bounded_text(
            error.get("code", "operation-error"),
            MAX_ERROR_CODE_CHARS,
            MAX_ERROR_CODE_BYTES,
        ),
        "task": None if task is None else _bounded_text(
            task,
            MAX_ERROR_TASK_CHARS,
            MAX_ERROR_TASK_BYTES,
        ),
        "message": _bounded_text(
            error.get("message", ""),
            MAX_ERROR_MESSAGE_CHARS,
            MAX_ERROR_MESSAGE_BYTES,
        ),
    }


def _bound_adapter_totals(value: object) -> dict[str, object]:
    """Accept only the fixed, bounded adapter aggregate shape."""
    if not isinstance(value, dict):
        return {}
    totals: dict[str, object] = {}
    for key in (
        "changed_records",
        "unchanged_records",
        "skipped_records",
        "fields_affected",
        "subfields_affected",
    ):
        count = value.get(key)
        if (
            isinstance(count, int)
            and not isinstance(count, bool)
            and 0 <= count <= 2_147_483_647
        ):
            totals[key] = count
    reasons = value.get("reason_codes")
    if isinstance(reasons, dict):
        bounded_reasons: dict[str, int] = {}
        for reason, count in reasons.items():
            if len(bounded_reasons) >= MAX_ADAPTER_REASON_CODES:
                break
            if not isinstance(reason, str):
                continue
            bounded_reason = _bounded_text(
                reason,
                MAX_ERROR_CODE_CHARS,
                MAX_ERROR_CODE_BYTES,
            )
            if (
                isinstance(count, int)
                and not isinstance(count, bool)
                and 0 <= count <= 2_147_483_647
            ):
                bounded_reasons[bounded_reason] = count
        totals["reason_codes"] = bounded_reasons
    return totals


def _bounded_text(value, max_chars: int, max_bytes: int) -> str:
    text = str(value).replace("\x00", "")[:max_chars]
    return text.encode("utf-8", "replace")[:max_bytes].decode(
        "utf-8", "ignore"
    )


def _read_bounded_file(path: Path, max_bytes: int) -> str:
    with path.open("rb") as source:
        return source.read(max_bytes).decode("utf-8", "replace")


def _read_bounded_stderr(path: Path) -> str:
    size = path.stat().st_size
    if size <= MAX_STDERR_BYTES:
        with path.open("rb") as source:
            return _decode_with_byte_cap(
                source.read(MAX_STDERR_BYTES),
                MAX_STDERR_BYTES,
            )
    marker = "\n...[stderr bytes omitted]...\n"
    marker_bytes = marker.encode("utf-8")
    remaining = MAX_STDERR_BYTES - len(marker_bytes)
    head_size = remaining // 2
    tail_size = remaining - head_size
    with path.open("rb") as source:
        head = source.read(head_size)
        source.seek(-tail_size, os.SEEK_END)
        tail = source.read(tail_size)
    return (
        _decode_with_byte_cap(head, head_size)
        + marker
        + _decode_with_byte_cap(tail, tail_size)
    )


def _decode_with_byte_cap(value: bytes, max_bytes: int) -> str:
    decoded = value.decode("utf-8", "replace")
    return decoded.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
