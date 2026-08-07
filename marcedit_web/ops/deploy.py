"""Lineage-driven production deploy for TASK-194."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class DeploymentError(ValueError):
    """A deployment preflight or contract error."""


@dataclass(frozen=True)
class DeploymentConfig:
    root: Path
    python: Path
    branch: str
    unit: str
    restart_target: str
    database: Path
    audit_dir: Path
    source_sha: str
    release_sha: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


_UNIT_NAME = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
_BRANCH_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_DIALOG_SIGNATURE = re.compile(r"^\(.*\)(?:\s*->\s*.+)?$", re.DOTALL)
_MIN_CAPTURE_STREAMLIT = (1, 37, 0)


def _result_stdout(value: Any) -> str:
    return str(value.get("stdout", "")) if isinstance(value, Mapping) else ""


def _result_ok(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("status") == "ok"


def _version(text: str) -> tuple[int, int, int]:
    match = _VERSION.search(text.strip())
    if not match:
        raise DeploymentError(f"could not parse dependency version: {text!r}")
    return tuple(int(part or 0) for part in match.groups())


def _unit_property(stdout: str, name: str) -> str:
    prefix = name + "="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return ""


def _environment_value(stdout: str, key: str) -> str:
    environment = _unit_property(stdout, "Environment")
    match = re.search(rf"(?:^|[\s;]){re.escape(key)}=([^;\s\n]+)", environment)
    return match.group(1).strip('"') if match else ""


def _authorized_restart_target(stdout: str, unit: str) -> str | None:
    candidates = (unit, unit.removesuffix(".service"))
    for candidate in candidates:
        command = re.escape(
            f"NOPASSWD: /bin/systemctl restart {candidate}"
        )
        if re.search(rf"(?:^|\s){command}(?:\s|$)", stdout):
            return candidate
    return None


def _runtime_python(exec_start: str) -> Path:
    match = re.search(r"(?:path|argv\[\])=([^ ;}]+)", exec_start)
    if not match:
        raise DeploymentError("captured unit has no executable path")
    executable = Path(match.group(1))
    if not executable.is_absolute():
        raise DeploymentError("captured runtime executable must be absolute")
    if executable.name == "streamlit":
        return executable.with_name("python")
    if executable.name == "python" or executable.name.startswith("python3"):
        return executable
    raise DeploymentError("captured unit executable is not Streamlit or Python")


def _database_from_capture(lineage: Mapping[str, Any], unit_output: str) -> Path:
    raw = lineage.get("database")
    if not _result_ok(raw):
        raise DeploymentError("database lineage capture is incomplete")
    try:
        details = json.loads(_result_stdout(raw))
    except (TypeError, ValueError) as exc:
        raise DeploymentError("database lineage capture is not valid JSON") from exc
    path = details.get("path")
    if not isinstance(path, str) or not path:
        raise DeploymentError("database lineage capture has no path")
    if not Path(path).is_absolute() or details.get("exists") is not True:
        raise DeploymentError("captured database path must be an existing absolute path")
    configured = _environment_value(unit_output, "MARCEDIT_WEB_DB_PATH")
    if configured and Path(configured) != Path(path):
        raise DeploymentError("database path disagrees with captured unit environment")
    return Path(path)


def validate_lineage(
    lineage: Mapping[str, Any],
    *,
    approved_branch: str,
    approved_release_sha: str,
) -> DeploymentConfig:
    """Validate Gate-0 facts and return the only safe deploy target."""
    if lineage.get("format") != "task-194-runtime-lineage-v1":
        raise DeploymentError("unsupported runtime-lineage format")
    if lineage.get("complete") is not True:
        errors = ", ".join(str(item) for item in lineage.get("capture_errors", []))
        raise DeploymentError(
            "runtime-lineage capture is incomplete"
            + (f": {errors}" if errors else "")
        )
    if (
        not isinstance(approved_branch, str)
        or not approved_branch.strip()
        or _BRANCH_NAME.fullmatch(approved_branch) is None
        or approved_branch.startswith("-")
    ):
        raise DeploymentError("approved branch must be a safe branch name")
    if (
        not isinstance(approved_release_sha, str)
        or re.fullmatch(r"[0-9a-fA-F]{40}", approved_release_sha) is None
    ):
        raise DeploymentError("approved release commit must be a 40-character SHA")

    root = Path(str(lineage.get("root", ""))).resolve()
    repository = lineage.get("repository")
    if not isinstance(repository, Mapping) or not _result_ok(repository.get("repository")):
        raise DeploymentError("repository root was not captured")
    captured_root = Path(_result_stdout(repository["repository"]).strip()).resolve()
    if captured_root != root:
        raise DeploymentError("lineage root does not match captured repository root")
    branch_result = repository.get("repository_branch")
    branch = _result_stdout(branch_result).strip()
    if not _result_ok(branch_result) or branch != approved_branch:
        raise DeploymentError(
            f"approved branch {approved_branch!r} does not match captured branch {branch!r}"
        )
    status_result = repository.get("repository_status")
    if not _result_ok(status_result) or _result_stdout(status_result).strip():
        raise DeploymentError("captured repository is not clean")
    sha_result = repository.get("repository_sha")
    source_sha = _result_stdout(sha_result).strip()
    if (
        not _result_ok(sha_result)
        or re.fullmatch(r"[0-9a-fA-F]{40}", source_sha) is None
    ):
        raise DeploymentError("captured repository commit is invalid")

    units = lineage.get("units")
    if not isinstance(units, Mapping):
        raise DeploymentError("unit lineage is missing")
    active_units = units.get("active_units")
    unit = units.get("selected_unit")
    if not isinstance(active_units, list) or len(active_units) != 1:
        raise DeploymentError("lineage must identify exactly one active unit")
    if unit != active_units[0] or not isinstance(unit, str) or not _UNIT_NAME.fullmatch(unit):
        raise DeploymentError("lineage selected unit is invalid or inconsistent")
    properties = units.get("properties")
    detail = properties.get(unit) if isinstance(properties, Mapping) else None
    if not _result_ok(detail):
        raise DeploymentError("selected unit properties were not captured")
    unit_output = _result_stdout(detail)
    if _unit_property(unit_output, "ActiveState") != "active":
        raise DeploymentError("selected unit is not active in the capture")
    python = _runtime_python(_unit_property(unit_output, "ExecStart"))
    database = _database_from_capture(lineage, unit_output)
    working_directory = _unit_property(unit_output, "WorkingDirectory")
    if not working_directory:
        raise DeploymentError("captured unit has no working directory")
    if Path(working_directory).resolve() != root:
        raise DeploymentError("captured working directory differs from repository root")
    audit_dir = Path(
        _environment_value(unit_output, "MARCEDIT_WEB_AUDIT_DIR")
        or str(root / "data" / "audit")
    )

    dependencies = lineage.get("dependencies")
    python_result = dependencies.get("python") if isinstance(dependencies, Mapping) else None
    if not _result_ok(python_result) or _version(_result_stdout(python_result))[:2] != (3, 9):
        raise DeploymentError("production Python 3.9 was not captured")
    streamlit = dependencies.get("streamlit") if isinstance(dependencies, Mapping) else None
    if not _result_ok(streamlit):
        raise DeploymentError("Streamlit dependency capture is incomplete")
    streamlit_version = _version(_result_stdout(streamlit))
    if not (_MIN_CAPTURE_STREAMLIT <= streamlit_version < (2, 0, 0)):
        raise DeploymentError(
            "captured Streamlit version is outside the supported upgrade "
            "range >=1.37,<2"
        )
    sqlite = lineage.get("sqlite")
    sqlite_result = sqlite.get("python_sqlite") if isinstance(sqlite, Mapping) else None
    if not _result_ok(sqlite_result) or _version(_result_stdout(sqlite_result)) < (3, 8, 0):
        raise DeploymentError("production SQLite lacks partial indexes")
    dialog = lineage.get("dialog")
    dialog_signature = _result_stdout(dialog).strip()
    if (
        not _result_ok(dialog)
        or _DIALOG_SIGNATURE.fullmatch(dialog_signature) is None
    ):
        raise DeploymentError("captured Streamlit dialog contract is missing")

    sudo = lineage.get("sudo")
    restart_target = (
        _authorized_restart_target(_result_stdout(sudo), unit)
        if _result_ok(sudo) else None
    )
    if restart_target is None:
        raise DeploymentError("service user lacks a NOPASSWD rule for the captured unit")
    return DeploymentConfig(
        root=root,
        python=python,
        branch=approved_branch,
        unit=unit,
        restart_target=restart_target,
        database=database,
        audit_dir=audit_dir,
        source_sha=source_sha.lower(),
        release_sha=approved_release_sha.lower(),
    )


def render_commands(
    config: DeploymentConfig,
    *,
    backup_dir: Path,
    health_url: str,
) -> tuple[tuple[str, ...], ...]:
    """Render the hotfix lifecycle with no worker or alternate-unit commands."""
    python = str(config.python)
    root = str(config.root)
    verify_release = (
        "import subprocess, sys; "
        f"root={json.dumps(root)}; "
        f"expected={json.dumps(config.release_sha)}; "
        "actual=subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD'], "
        "text=True).strip().lower(); "
        "sys.exit(0 if actual == expected else "
        "'approved release SHA mismatch: ' + actual)"
    )
    return (
        ("git", "-C", root, "pull", "--ff-only", "origin", config.branch),
        (python, "-c", verify_release),
        (python, "-m", "pip", "install", "--upgrade", "pip"),
        (python, "-m", "pip", "install", "-r", str(config.root / "requirements.txt")),
        (
            python,
            "-c",
            "import inspect, streamlit; "
            "assert (1, 50) <= tuple(map(int, streamlit.__version__.split('.')[:2])) < (2, 0); "
            "assert 'dismissible' in inspect.signature(streamlit.dialog).parameters",
        ),
        (
            "env",
            f"MARCEDIT_WEB_DB_PATH={config.database}",
            f"MARCEDIT_WEB_AUDIT_DIR={config.audit_dir}",
            python,
            "-m",
            "marcedit_web.ops.backup",
            "create",
            str(backup_dir),
        ),
        (
            "env",
            f"MARCEDIT_WEB_DB_PATH={config.database}",
            python,
            "-m",
            "marcedit_web.ops.health",
        ),
        ("sudo", "/bin/systemctl", "restart", config.restart_target),
        ("curl", "-fs", health_url),
    )


def verify_repository_state(
    config: DeploymentConfig,
    *,
    runner=subprocess.run,
) -> None:
    """Refuse to pull when the checkout changed after Gate 0."""
    status = runner(
        ["git", "-C", str(config.root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise DeploymentError("could not read repository status")
    if status.stdout.strip():
        raise DeploymentError("repository must be clean before deployment")
    branch = runner(
        ["git", "-C", str(config.root), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    if branch.returncode != 0 or branch.stdout.strip() != config.branch:
        raise DeploymentError(
            f"repository branch changed; expected {config.branch!r}"
        )
    commit = runner(
        ["git", "-C", str(config.root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0 or commit.stdout.strip().lower() != config.source_sha:
        raise DeploymentError(
            "repository commit changed after Gate 0; expected "
            f"{config.source_sha}"
        )


def _run(commands: Sequence[Sequence[str]], *, root: Path, dry_run: bool) -> None:
    for command in commands:
        rendered = shlex.join(list(command))
        if dry_run:
            print(f"DRY RUN: {rendered}")
            continue
        subprocess.run(list(command), cwd=root, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a lineage-driven TASK-194 deploy.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument(
        "--health-url",
        default="http://127.0.0.1:8501/marcedit-web/_stcore/health",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        lineage = json.loads(args.lineage.read_text(encoding="utf-8"))
        config = validate_lineage(
            lineage,
            approved_branch=args.branch,
            approved_release_sha=args.release_sha,
        )
        if config.root != args.root.resolve():
            raise DeploymentError("--root does not match the captured repository root")
        if not args.dry_run:
            verify_repository_state(config)
        _run(
            render_commands(
                config,
                backup_dir=args.backup_dir,
                health_url=args.health_url,
            ),
            root=config.root,
            dry_run=args.dry_run,
        )
        return 0
    except (DeploymentError, OSError, subprocess.CalledProcessError) as exc:
        print(f"deploy preflight failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
