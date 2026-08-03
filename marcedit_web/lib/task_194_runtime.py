"""Read-only production runtime-lineage capture for TASK-194."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


Runner = Callable[[Sequence[str]], Mapping[str, Any]]


def _run(command: Sequence[str]) -> Mapping[str, Any]:
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _capture(command: Sequence[str], runner: Runner) -> dict[str, Any]:
    raw = dict(runner(command))
    return {
        "command": list(command),
        "status": "ok" if int(raw.get("returncode", 1)) == 0 else "failed",
        "returncode": int(raw.get("returncode", 1)),
        "stdout": str(raw.get("stdout", "")),
        "stderr": str(raw.get("stderr", "")),
    }


def capture_lineage(root: Path, *, runner: Runner = _run) -> dict[str, Any]:
    """Collect all Gate-0 facts without changing repository or services."""
    root = root.resolve()
    python = str(root / ".venv" / "bin" / "python")
    database = str(root / "data" / "marcedit.db")
    commands: dict[str, Sequence[str]] = {
        "repository": ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        "repository_status": ["git", "-C", str(root), "status", "--short"],
        "repository_branch": ["git", "-C", str(root), "branch", "--show-current"],
        "repository_sha": ["git", "-C", str(root), "rev-parse", "HEAD"],
        "units": ["systemctl", "list-unit-files", "marcedit-web*.service", "--no-legend"],
        "unit_properties": [
            "systemctl", "show", "marcedit-web.service",
            "-p", "ActiveState,UnitFileState,FragmentPath,WorkingDirectory,ExecStart,User,Group,EnvironmentFile",
        ],
        "sudo": ["sudo", "-n", "-l"],
        "python": [python, "--version"],
        "streamlit": [python, "-c", "import streamlit; print(streamlit.__version__)"],
        "pymarc": [python, "-c", "import pymarc; print(pymarc.__version__)"],
        "python_sqlite": [python, "-c", "import sqlite3; print(sqlite3.sqlite_version)"],
        "sqlite_cli": ["sqlite3", "--version"],
        "dialog": [
            python, "-c",
            "import inspect, streamlit; print(inspect.signature(streamlit.dialog))",
        ],
        "database": [
            python, "-c",
            (
                "import json, pathlib, os; "
                f"p=pathlib.Path({database!r}); "
                "print(json.dumps({'path':str(p),'exists':p.exists(),'size':p.stat().st_size if p.exists() else None,'mode':oct(p.stat().st_mode) if p.exists() else None}))"
            ),
        ],
    }
    captured = {name: _capture(command, runner) for name, command in commands.items()}
    return {
        "format": "task-194-runtime-lineage-v1",
        "root": str(root),
        "repository": {
            key: captured[key] for key in (
                "repository", "repository_status", "repository_branch", "repository_sha"
            )
        },
        "units": {
            key: captured[key] for key in ("units", "unit_properties")
        },
        "sudo": captured["sudo"],
        "dependencies": {
            key: captured[key] for key in ("python", "streamlit", "pymarc")
        },
        "sqlite": {
            key: captured[key] for key in ("python_sqlite", "sqlite_cli")
        },
        "database": captured["database"],
        "dialog": captured["dialog"],
    }


def write_lineage(path: Path, lineage: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(lineage), indent=2, sort_keys=True) + "\n")

