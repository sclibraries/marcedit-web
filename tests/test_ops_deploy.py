"""Tests for the lineage-driven TASK-194 deployment entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marcedit_web.ops import deploy


def _lineage(tmp_path: Path) -> dict:
    root = tmp_path / "checkout"
    python = root / ".venv" / "bin" / "python"
    db_path = root / "data" / "marcedit.db"
    return {
        "format": "task-194-runtime-lineage-v1",
        "complete": True,
        "root": str(root),
        "capture_errors": [],
        "repository": {
            "repository": {"status": "ok", "stdout": str(root)},
            "repository_branch": {"status": "ok", "stdout": "release-hotfix\n"},
            "repository_sha": {"status": "ok", "stdout": "a" * 40},
        },
        "units": {
            "active_units": ["catalog.service"],
            "selected_unit": "catalog.service",
            "properties": {
                "catalog.service": {
                    "status": "ok",
                    "stdout": (
                        "ActiveState=active\n"
                        "WorkingDirectory=" + str(root) + "\n"
                        "ExecStart={ path=" + str(root / ".venv" / "bin" / "streamlit") + " ; argv[]=" + str(root / ".venv" / "bin" / "streamlit") + " }\n"
                        "EnvironmentFile=" + str(root / ".env") + "\n"
                        "Environment=MARCEDIT_WEB_DB_PATH=" + str(db_path)
                        + " MARCEDIT_WEB_AUDIT_DIR=" + str(root / "data" / "audit") + "\n"
                    ),
                }
            },
        },
        "sudo": {
            "status": "ok",
            "stdout": "    (root) NOPASSWD: /bin/systemctl restart catalog.service\n",
        },
        "dependencies": {
            "python": {"status": "ok", "stdout": "Python 3.9.25\n"},
            "streamlit": {"status": "ok", "stdout": "1.50.0\n"},
            "pymarc": {"status": "ok", "stdout": "5.2.3\n"},
        },
        "sqlite": {
            "python_sqlite": {"status": "ok", "stdout": "3.40.1\n"},
        },
        "dialog": {
            "status": "ok",
            "stdout": "(title, *, width='small', dismissible=True, on_dismiss='ignore')\n",
        },
        "database": {
            "status": "ok",
            "stdout": json.dumps({"path": str(db_path), "exists": True}),
        },
    }


def test_validate_lineage_requires_one_captured_active_unit(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["units"]["active_units"] = ["catalog.service", "catalog-public.service"]

    with pytest.raises(deploy.DeploymentError, match="exactly one active unit"):
        deploy.validate_lineage(lineage, approved_branch="release-hotfix")


def test_validate_lineage_checks_streamlit_dialog_and_sudo_contract(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["dialog"]["stdout"] = "(title, *, width='small')\n"

    with pytest.raises(deploy.DeploymentError, match="dismissible"):
        deploy.validate_lineage(lineage, approved_branch="release-hotfix")


@pytest.mark.parametrize("branch", ["--danger", "release hotfix"])
def test_validate_lineage_rejects_unsafe_branch_names(tmp_path, branch):
    with pytest.raises(deploy.DeploymentError, match="branch"):
        deploy.validate_lineage(_lineage(tmp_path), approved_branch=branch)


def test_validate_lineage_requires_python39_sqlite_partial_index_and_nopasswd(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["dependencies"]["python"]["stdout"] = "Python 3.10.1\n"

    with pytest.raises(deploy.DeploymentError, match="Python 3.9"):
        deploy.validate_lineage(lineage, approved_branch="release-hotfix")

    lineage = _lineage(tmp_path)
    lineage["sqlite"] = {"python_sqlite": {"status": "ok", "stdout": "3.7.0\n"}}
    with pytest.raises(deploy.DeploymentError, match="partial indexes"):
        deploy.validate_lineage(lineage, approved_branch="release-hotfix")

    lineage = _lineage(tmp_path)
    lineage["sudo"]["stdout"] = "(root) /bin/systemctl restart catalog.service\n"
    with pytest.raises(deploy.DeploymentError, match="NOPASSWD"):
        deploy.validate_lineage(lineage, approved_branch="release-hotfix")


def test_render_commands_uses_captured_unit_and_has_no_worker_lifecycle(tmp_path):
    config = deploy.validate_lineage(
        _lineage(tmp_path), approved_branch="release-hotfix"
    )

    commands = deploy.render_commands(
        config,
        backup_dir=tmp_path / "backup",
        health_url="http://127.0.0.1:8501/marcedit-web/_stcore/health",
    )
    rendered = "\n".join(" ".join(command) for command in commands)

    assert "catalog.service" in rendered
    assert "release-hotfix" in rendered
    assert "marcedit-web-worker" not in rendered
    assert "marcedit-web-private" not in rendered
    assert "git -C " + str(config.root) + " pull --ff-only origin release-hotfix" in rendered
    assert "pip install -r " + str(config.root / "requirements.txt") in rendered
    assert "marcedit_web.ops.backup create " + str(tmp_path / "backup") in rendered
    assert f"MARCEDIT_WEB_DB_PATH={config.database}" in rendered


def test_apply_preflight_rejects_a_dirty_or_different_branch(tmp_path):
    config = deploy.validate_lineage(
        _lineage(tmp_path), approved_branch="release-hotfix"
    )

    def dirty_runner(command, **_kwargs):
        if command[-2:] == ["branch", "--show-current"]:
            return deploy.CommandResult(0, "other-branch\n", "")
        return deploy.CommandResult(0, " M app.py\n", "")

    with pytest.raises(deploy.DeploymentError, match="clean"):
        deploy.verify_repository_state(config, runner=dirty_runner)


def test_apply_preflight_rejects_branch_drift_even_when_clean(tmp_path):
    config = deploy.validate_lineage(
        _lineage(tmp_path), approved_branch="release-hotfix"
    )

    def branch_runner(command, **_kwargs):
        if command[-2:] == ["branch", "--show-current"]:
            return deploy.CommandResult(0, "other-branch\n", "")
        return deploy.CommandResult(0, "", "")

    with pytest.raises(deploy.DeploymentError, match="branch"):
        deploy.verify_repository_state(config, runner=branch_runner)


def test_deploy_cli_dry_run_does_not_execute_commands(tmp_path, capsys):
    lineage_path = tmp_path / "lineage.json"
    lineage_path.write_text(json.dumps(_lineage(tmp_path)))

    exit_code = deploy.main(
        [
            "--root", str(tmp_path / "checkout"),
            "--lineage", str(lineage_path),
            "--branch", "release-hotfix",
            "--backup-dir", str(tmp_path / "backup"),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert "systemctl restart catalog.service" in output
    assert not (tmp_path / "backup").exists()
