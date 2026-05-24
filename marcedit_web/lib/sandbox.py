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

Stage 21 will add per-process cgroup isolation when the container is
hardened.
"""

from __future__ import annotations

import json
import logging
import os
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("marcedit_web.sandbox")


# Bytes-per-resource ceilings. Tuned for "100K records of small/medium
# pymarc.Record objects fits in 512 MB" — there's some headroom for
# pymarc + marcedit_web import overhead.
_CPU_SECONDS = 30
_AS_BYTES = 512 * 1024 * 1024     # 512 MB virtual memory
_FSIZE_BYTES = 1024 * 1024 * 1024  # 1 GB single-file write cap
_NPROC = 32                        # subprocess can't fork-bomb


@dataclass
class TaskSpec:
    """One task to run, in order, against every record."""

    name: str
    body: str
    imports: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    """Outcome of a single sandbox invocation.

    ``records_bytes`` is the MARC blob the child produced (possibly
    empty when the run failed before any record was written).
    ``errors`` is the structured per-record diagnostic list. ``stderr``
    is the raw child stderr — surfaced for debugging when the run
    failed outside the per-record loop (import error, segfault, etc).
    ``timed_out`` is True when the wall clock cap fired.
    """

    records_bytes: bytes
    errors: list[dict]
    stderr: str = ""
    returncode: int = 0
    timed_out: bool = False


# Inlined driver script — passed via -c to the child. Kept here so the
# sandbox is self-contained (no separate file to ship + path issues
# inside the container).
_DRIVER_SCRIPT = r"""
import argparse
import io
import json
import os
import resource
import sys
import traceback

# Defensive re-set of rlimits inside the child. The parent's preexec_fn
# also sets these; we duplicate here so the limits are visible if
# someone bypasses preexec.
def _set_limits():
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,
                                                 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024 * 1024,
                                                    1024 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except (ValueError, resource.error):
        # Already at the limit or unsupported; not fatal.
        pass

_set_limits()

import pymarc
from marcedit_web.lib import transforms  # standard helpers in scope


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--errors", required=True)
    args = ap.parse_args()

    with open(args.tasks) as f:
        tasks = json.load(f)

    errors = []
    with open(args.input, "rb") as fin:
        reader = pymarc.MARCReader(fin, to_unicode=True, permissive=True)
        with open(args.output, "wb") as fout:
            writer = pymarc.MARCWriter(fout)
            for idx, record in enumerate(reader, start=1):
                if record is None:
                    errors.append({
                        "index": idx,
                        "code": "malformed-record",
                        "task": None,
                        "message": "pymarc skipped a malformed record",
                    })
                    continue
                failed_task = None
                try:
                    for task in tasks:
                        # Fresh namespace per task so symbols don't leak.
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
                        # Imports requested by the task (e.g. specific
                        # transforms helpers) — run first.
                        for imp in task.get("imports", []):
                            exec(compile(imp, "<task-import>", "exec"), ns)
                        exec(compile(
                            task["body"],
                            "<task:%s>" % task.get("name", "?"),
                            "exec",
                        ), ns)
                    writer.write(record)
                except Exception as exc:
                    failed_task = task.get("name", "?") if 'task' in locals() else "?"
                    errors.append({
                        "index": idx,
                        "code": "transform-failed",
                        "task": failed_task,
                        "message": "%s: %s" % (type(exc).__name__, exc),
                    })
                    # Keep original record so the output batch stays the
                    # same cardinality as the input.
                    writer.write(record)

    with open(args.errors, "w") as f:
        json.dump(errors, f)


if __name__ == "__main__":
    main()
"""


def _preexec_set_limits() -> None:
    """preexec_fn for the parent's Popen.

    Runs in the child between fork() and exec(); the limits stick to
    the new process and any of its descendants.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (_AS_BYTES, _AS_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (_NPROC, _NPROC))


def run_tasks_subprocess(
    tasks: Iterable[TaskSpec],
    record_bytes: bytes,
    *,
    timeout: float = 30.0,
    tmp_dir: Optional[Path] = None,
) -> SandboxResult:
    """Apply ``tasks`` (in order) to every record in ``record_bytes``.

    Spawns a child Python with rlimits, hands it the inputs via temp
    files, captures the MARC output + JSON error log. Never raises on
    user-task errors — those land in ``SandboxResult.errors``. Raises
    ``RuntimeError`` only on launcher-level problems (can't write the
    temp files, can't spawn python at all).
    """
    tasks_list = [
        {"name": t.name, "body": t.body, "imports": list(t.imports)}
        for t in tasks
    ]

    workdir = (
        tmp_dir
        if tmp_dir is not None
        else Path(tempfile.mkdtemp(prefix="marcedit-web-sandbox-"))
    )
    workdir.mkdir(parents=True, exist_ok=True)
    input_path = workdir / "input.mrc"
    tasks_path = workdir / "tasks.json"
    output_path = workdir / "output.mrc"
    errors_path = workdir / "errors.json"

    input_path.write_bytes(record_bytes)
    tasks_path.write_text(json.dumps(tasks_list))

    cmd = [
        sys.executable,
        "-c",
        _DRIVER_SCRIPT,
        "--input", str(input_path),
        "--tasks", str(tasks_path),
        "--output", str(output_path),
        "--errors", str(errors_path),
    ]
    # Cleansed environment: PYTHONPATH (for marcedit_web imports),
    # PATH (for the python invocation), HOME (some libraries demand
    # one). Nothing else.
    env = {
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workdir),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    timed_out = False
    stderr = ""
    returncode = 0
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(workdir),
            env=env,
            preexec_fn=_preexec_set_limits,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stderr = completed.stderr
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        logger.warning("sandbox timed out after %.1fs", timeout)
    except FileNotFoundError as exc:
        # The python interpreter wasn't found — that's a launcher bug.
        raise RuntimeError(f"sandbox could not spawn python: {exc}") from exc

    out_bytes = output_path.read_bytes() if output_path.exists() else b""
    try:
        errors = json.loads(errors_path.read_text()) if errors_path.exists() else []
    except json.JSONDecodeError:
        errors = []

    if timed_out:
        errors.append({
            "index": 0,
            "code": "sandbox-timeout",
            "task": None,
            "message": f"sandbox exceeded {timeout:.0f}s wall clock",
        })
    elif returncode != 0:
        errors.append({
            "index": 0,
            "code": "sandbox-nonzero-exit",
            "task": None,
            "message": (
                f"sandbox exited with code {returncode}. stderr: "
                f"{stderr.strip()[:1024]}"
            ),
        })

    return SandboxResult(
        records_bytes=out_bytes,
        errors=errors,
        stderr=stderr,
        returncode=returncode,
        timed_out=timed_out,
    )
