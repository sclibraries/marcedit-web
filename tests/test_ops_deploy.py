"""Tests for the lineage-driven TASK-194 deployment entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
            "repository_status": {"status": "ok", "stdout": ""},
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
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )


def test_validate_lineage_checks_streamlit_dialog_and_sudo_contract(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["dialog"]["stdout"] = ""

    with pytest.raises(deploy.DeploymentError, match="dialog contract"):
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )


def test_validate_lineage_rejects_a_non_signature_dialog_capture(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["dialog"]["stdout"] = "streamlit dialog unavailable"

    with pytest.raises(deploy.DeploymentError, match="dialog contract"):
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )


def test_validate_lineage_allows_upgradeable_streamlit_before_restart(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["dependencies"]["streamlit"]["stdout"] = "1.37.0\n"
    lineage["dialog"]["stdout"] = "(title, *, width='small')\n"

    config = deploy.validate_lineage(
        lineage,
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )

    assert config.unit == "catalog.service"


def test_validate_lineage_accepts_annotated_streamlit_dialog_signature(tmp_path):
    """Python 3.9 renders Streamlit 1.50's return annotation after ``)``."""
    lineage = _lineage(tmp_path)
    lineage["dialog"]["stdout"] = (
        "(title: 'F | str', *, width: 'DialogWidth' = 'small', "
        "dismissible: 'bool' = True, on_dismiss: \"Literal['ignore', "
        "'rerun'] | WidgetCallback\" = 'ignore') -> "
        "'F | Callable[[F], F]'\n"
    )

    config = deploy.validate_lineage(
        lineage,
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )

    assert config.unit == "catalog.service"


@pytest.mark.parametrize("branch", ["--danger", "release hotfix"])
def test_validate_lineage_rejects_unsafe_branch_names(tmp_path, branch):
    with pytest.raises(deploy.DeploymentError, match="branch"):
        deploy.validate_lineage(
            _lineage(tmp_path),
            approved_branch=branch,
            approved_release_sha="b" * 40,
        )


def test_validate_lineage_requires_python39_sqlite_partial_index_and_nopasswd(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["dependencies"]["python"]["stdout"] = "Python 3.10.1\n"

    with pytest.raises(deploy.DeploymentError, match="Python 3.9"):
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )

    lineage = _lineage(tmp_path)
    lineage["sqlite"] = {"python_sqlite": {"status": "ok", "stdout": "3.7.0\n"}}
    with pytest.raises(deploy.DeploymentError, match="partial indexes"):
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )

    lineage = _lineage(tmp_path)
    lineage["sudo"]["stdout"] = "(root) /bin/systemctl restart catalog.service\n"
    with pytest.raises(deploy.DeploymentError, match="NOPASSWD"):
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )


def test_validate_lineage_uses_suffixless_unit_authorized_by_sudoers(tmp_path):
    """Production sudoers authorizes ``catalog`` for ``catalog.service``."""
    lineage = _lineage(tmp_path)
    lineage["sudo"]["stdout"] = (
        "    (root) NOPASSWD: /bin/systemctl restart catalog\n"
    )

    config = deploy.validate_lineage(
        lineage,
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )
    commands = deploy.render_commands(
        config,
        backup_dir=tmp_path / "backup",
        health_url="http://127.0.0.1:8501/health",
    )

    assert config.unit == "catalog.service"
    assert ("sudo", "/bin/systemctl", "restart", "catalog") in commands


def test_validate_lineage_requires_captured_working_directory(tmp_path):
    lineage = _lineage(tmp_path)
    properties = lineage["units"]["properties"]["catalog.service"]
    properties["stdout"] = properties["stdout"].replace(
        "WorkingDirectory=" + str(tmp_path / "checkout") + "\n",
        "",
    )

    with pytest.raises(deploy.DeploymentError, match="working directory"):
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )


def test_render_commands_uses_captured_unit_and_has_no_worker_lifecycle(tmp_path):
    config = deploy.validate_lineage(
        _lineage(tmp_path),
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
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
        _lineage(tmp_path),
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )

    def dirty_runner(command, **_kwargs):
        if command[-2:] == ["branch", "--show-current"]:
            return deploy.CommandResult(0, "other-branch\n", "")
        return deploy.CommandResult(0, " M app.py\n", "")

    with pytest.raises(deploy.DeploymentError, match="clean"):
        deploy.verify_repository_state(config, runner=dirty_runner)


def test_apply_preflight_rejects_branch_drift_even_when_clean(tmp_path):
    config = deploy.validate_lineage(
        _lineage(tmp_path),
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )

    def branch_runner(command, **_kwargs):
        if command[-2:] == ["branch", "--show-current"]:
            return deploy.CommandResult(0, "other-branch\n", "")
        return deploy.CommandResult(0, "", "")

    with pytest.raises(deploy.DeploymentError, match="branch"):
        deploy.verify_repository_state(config, runner=branch_runner)


def test_apply_preflight_rejects_commit_drift_even_when_branch_is_clean(tmp_path):
    config = deploy.validate_lineage(
        _lineage(tmp_path),
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )

    def commit_runner(command, **_kwargs):
        if command[-2:] == ["branch", "--show-current"]:
            return deploy.CommandResult(0, "release-hotfix\n", "")
        if command[-3:] == ["rev-parse", "HEAD"]:
            return deploy.CommandResult(0, "b" * 40 + "\n", "")
        return deploy.CommandResult(0, "", "")

    with pytest.raises(deploy.DeploymentError, match="commit"):
        deploy.verify_repository_state(config, runner=commit_runner)


def test_validate_lineage_requires_a_valid_approved_release_sha(tmp_path):
    with pytest.raises(deploy.DeploymentError, match="release commit"):
        deploy.validate_lineage(
            _lineage(tmp_path),
            approved_branch="release-hotfix",
            approved_release_sha="not-a-sha",
        )


def test_render_commands_verify_the_approved_release_after_pull(tmp_path):
    config = deploy.validate_lineage(
        _lineage(tmp_path),
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )

    commands = deploy.render_commands(
        config,
        backup_dir=tmp_path / "backup",
        health_url="http://127.0.0.1:8501/marcedit-web/_stcore/health",
    )
    pull_index = next(
        index for index, command in enumerate(commands)
        if command[:5] == ("git", "-C", str(config.root), "pull", "--ff-only")
    )
    verify_index = next(
        index for index, command in enumerate(commands)
        if "rev-parse" in " ".join(command)
        and "b" * 40 in " ".join(command)
    )
    assert verify_index == pull_index + 1


def test_release_sha_check_rejects_mismatch_before_following_commands(
    tmp_path, monkeypatch
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!{python}\n"
        "import sys\n"
        "if sys.argv[-2:] == ['rev-parse', 'HEAD']:\n"
        "    print('a' * 40)\n"
        "else:\n"
        "    raise SystemExit('unexpected fake git command')\n".format(
            python=sys.executable,
        )
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
    )
    config = deploy.validate_lineage(
        _lineage(tmp_path),
        approved_branch="release-hotfix",
        approved_release_sha="b" * 40,
    )
    verify = deploy.render_commands(
        config,
        backup_dir=tmp_path / "backup",
        health_url="http://localhost",
    )[1]
    verify = (sys.executable, "-c", verify[2])
    sentinel = tmp_path / "sentinel"
    follow_up = (
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(sentinel)!r}).write_text('ran')",
    )

    with pytest.raises(subprocess.CalledProcessError):
        deploy._run([verify, follow_up], root=checkout, dry_run=False)
    assert not sentinel.exists()


def test_validate_lineage_requires_a_clean_captured_checkout(tmp_path):
    lineage = _lineage(tmp_path)
    lineage["repository"]["repository_status"]["stdout"] = " M app.py\n"

    with pytest.raises(deploy.DeploymentError, match="captured repository"):
        deploy.validate_lineage(
            lineage,
            approved_branch="release-hotfix",
            approved_release_sha="b" * 40,
        )


def test_deploy_cli_dry_run_does_not_execute_commands(tmp_path, capsys):
    lineage_path = tmp_path / "lineage.json"
    lineage_path.write_text(json.dumps(_lineage(tmp_path)))

    exit_code = deploy.main(
        [
            "--root", str(tmp_path / "checkout"),
            "--lineage", str(lineage_path),
            "--branch", "release-hotfix",
            "--release-sha", "b" * 40,
            "--backup-dir", str(tmp_path / "backup"),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert "systemctl restart catalog.service" in output
    assert not (tmp_path / "backup").exists()
