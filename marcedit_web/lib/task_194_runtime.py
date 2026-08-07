"""Read-only production runtime-lineage capture for TASK-194."""

from __future__ import annotations

import json
import re
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


def _failed_capture(message: str) -> dict[str, Any]:
    """Represent a fact that could not be discovered without running a guess."""
    return {
        "command": [],
        "status": "failed",
        "returncode": 1,
        "stdout": "",
        "stderr": message,
    }


def _unit_names(stdout: str) -> list[str]:
    return sorted({
        line.split()[0]
        for line in stdout.splitlines()
        if line.split() and line.split()[0].endswith(".service")
    })


def _property(stdout: str, name: str) -> str:
    prefix = name + "="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return ""


def _runtime_python(exec_start: str) -> str | None:
    match = re.search(r"(?:path|argv\[\])=([^ ;}]+)", exec_start)
    if match:
        executable = Path(match.group(1))
        if executable.name == "streamlit":
            return str(executable.with_name("python"))
        if executable.name == "python" or executable.name.startswith("python3"):
            return str(executable)
    return None


def _database_path(unit_output: str, root: Path) -> str:
    environment = _property(unit_output, "Environment")
    match = re.search(
        r"(?:^|[\s;])MARCEDIT_WEB_DB_PATH=([^;\s\n]+)",
        environment,
    )
    if match:
        return match.group(1).strip().strip('"')
    working_directory = _property(unit_output, "WorkingDirectory")
    base = Path(working_directory) if working_directory else root
    return str(base / "data" / "marcedit.db")


def capture_lineage(root: Path, *, runner: Runner = _run) -> dict[str, Any]:
    """Collect all Gate-0 facts without changing repository or services."""
    root = root.resolve()
    captured: dict[str, dict[str, Any]] = {}
    repository_commands: dict[str, Sequence[str]] = {
        "repository": ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        "repository_status": ["git", "-C", str(root), "status", "--short"],
        "repository_branch": ["git", "-C", str(root), "branch", "--show-current"],
        "repository_sha": ["git", "-C", str(root), "rev-parse", "HEAD"],
    }
    for name, command in repository_commands.items():
        captured[name] = _capture(command, runner)

    captured["remote_url"] = _capture(
        ["git", "-C", str(root), "remote", "get-url", "origin"], runner
    )
    captured["sudo"] = _capture(["sudo", "-n", "-l"], runner)
    captured["units"] = _capture(
        ["systemctl", "list-unit-files", "marcedit-web*.service", "--no-legend"],
        runner,
    )
    names = _unit_names(captured["units"]["stdout"])
    unit_details: dict[str, dict[str, Any]] = {}
    for name in names:
        unit_details[name] = _capture(
            [
                "systemctl", "show", name,
                "-p",
                "ActiveState,UnitFileState,FragmentPath,WorkingDirectory,ExecStart,User,Group,EnvironmentFile,Environment",
            ],
            runner,
        )
    active_units = [
        name for name in names
        if _property(unit_details[name]["stdout"], "ActiveState") == "active"
    ]
    # Choosing the first active unit is unsafe on hosts that expose both the
    # public and private tiers.  Gate 0 must identify one exact unit from
    # operator evidence before a deployment plan can target it.
    selected_unit = active_units[0] if len(active_units) == 1 else None
    selected_output = unit_details[selected_unit]["stdout"] if selected_unit else ""
    python = (
        _runtime_python(_property(selected_output, "ExecStart"))
        if selected_unit and unit_details[selected_unit]["status"] == "ok" else None
    )
    database = _database_path(selected_output, root) if selected_unit else None
    dependency_commands: dict[str, Sequence[str]] = {
        "python": [python, "--version"],
        "streamlit": [python, "-c", "import streamlit; print(streamlit.__version__)"],
        "pymarc": [
            python,
            "-c",
            (
                "import importlib.metadata, pymarc; "
                "print(importlib.metadata.version('pymarc'))"
            ),
        ],
        "pip_inventory": [python, "-m", "pip", "list", "--format=json"],
        "python_sqlite": [python, "-c", "import sqlite3; print(sqlite3.sqlite_version)"],
        "sqlite_cli": ["sqlite3", "--version"],
        "dialog": [
            python, "-c",
            "import inspect, streamlit; print(inspect.signature(streamlit.dialog))",
        ],
        "database": [
            python, "-c",
            (
                "import json, pathlib, shutil, sqlite3; "
                f"p=pathlib.Path({database!r}); "
                "payload={'path':str(p),'exists':p.exists(),'size':p.stat().st_size if p.exists() else None,'mode':oct(p.stat().st_mode) if p.exists() else None,'free_bytes':shutil.disk_usage(p.parent).free,'tables':[r[0] for r in sqlite3.connect(p).execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")] if p.exists() else []}; "
                "print(json.dumps(payload))"
            ),
        ],
    }
    if python is None:
        for name in dependency_commands:
            captured[name] = _failed_capture(
                "runtime unit is not uniquely identified"
            )
    else:
        for name, command in dependency_commands.items():
            captured[name] = _capture(command, runner)
    capture_errors = [
        name for name, value in captured.items()
        if value["status"] != "ok"
    ]
    capture_errors.extend(
        f"unit:{name}"
        for name, value in unit_details.items()
        if value["status"] != "ok"
    )
    if not selected_unit:
        capture_errors.append(
            "active_unit_ambiguous" if len(active_units) > 1 else "active_unit"
        )
    return {
        "format": "task-194-runtime-lineage-v1",
        "root": str(root),
        "complete": not capture_errors,
        "capture_errors": sorted(set(capture_errors)),
        "repository": {
            **{key: captured[key] for key in repository_commands},
            "remote_url": captured["remote_url"],
        },
        "units": {
            "list": captured["units"],
            "active_units": active_units,
            "selected_unit": selected_unit,
            "properties": unit_details,
        },
        "sudo": captured["sudo"],
        "dependencies": {
            key: captured[key] for key in (
                "python", "streamlit", "pymarc", "pip_inventory"
            )
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
