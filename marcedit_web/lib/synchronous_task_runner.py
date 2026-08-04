"""Synchronous saved-task execution for the TASK-194 hotfix."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Iterable

from . import sandbox


@dataclass(frozen=True)
class SyncRun:
    input_path: Path
    output_path: Path
    workdir: Path
    result: sandbox.SandboxResult


def run_tasks(
    input_path: Path,
    tasks: Iterable[sandbox.TaskSpec],
    *,
    tmp_dir: Path | None = None,
) -> SyncRun:
    """Run saved task specs through one bounded sandbox invocation.

    This path intentionally has no database operation row, worker lease, or
    operation-submission call. The caller owns the returned workdir until the
    result is downloaded, applied, or discarded.
    """
    input_path = Path(input_path)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    workdir = (
        Path(tmp_dir)
        if tmp_dir is not None
        else Path(tempfile.mkdtemp(prefix="marcedit-web-sync-"))
    )
    workdir.mkdir(parents=True, exist_ok=True)
    result = sandbox.run_tasks_subprocess(
        list(tasks),
        input_path=input_path,
        tmp_dir=workdir,
    )
    return SyncRun(
        input_path=input_path,
        output_path=result.output_path,
        workdir=workdir,
        result=result,
    )
