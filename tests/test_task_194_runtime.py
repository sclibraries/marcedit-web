"""Read-only runtime-lineage capture contract for TASK-194."""

from pathlib import Path
import os
import subprocess

from marcedit_web.lib import task_194_runtime


def test_capture_plan_is_read_only_and_records_required_runtime_domains(tmp_path):
    commands = []

    def runner(command):
        commands.append(tuple(command))
        return {"returncode": 0, "stdout": "captured", "stderr": ""}

    result = task_194_runtime.capture_lineage(Path(tmp_path), runner=runner)

    assert {
        "repository",
        "units",
        "sudo",
        "dependencies",
        "sqlite",
        "database",
        "dialog",
    } <= set(result)
    forbidden = {"pull", "restart", "stop", "start", "enable", "disable"}
    assert not any(
        any(token in part for token in forbidden)
        for command in commands
        for part in command
    )


def test_capture_lineage_serializes_command_failures_without_raising(tmp_path):
    def runner(command):
        return {"returncode": 1, "stdout": "", "stderr": "not available"}

    result = task_194_runtime.capture_lineage(Path(tmp_path), runner=runner)

    assert result["repository"]["repository"]["status"] == "failed"
    assert result["repository"]["repository"]["stderr"] == "not available"


def test_capture_lineage_uses_the_discovered_unit_and_runtime_python(tmp_path):
    commands = []

    def runner(command):
        commands.append(tuple(command))
        if list(command[:3]) == ["systemctl", "list-unit-files", "marcedit-web*.service"]:
            return {
                "returncode": 0,
                "stdout": "marcedit-web-private.service enabled\n",
                "stderr": "",
            }
        if list(command[:2]) == ["systemctl", "show"]:
            return {
                "returncode": 0,
                "stdout": (
                    "ActiveState=active\n"
                    "ExecStart={ path=/opt/marcedit/.venv/bin/streamlit ; argv[]=/opt/marcedit/.venv/bin/streamlit }\n"
                    "WorkingDirectory=/opt/marcedit\n"
                    "EnvironmentFile=/opt/marcedit/.env\n"
                ),
                "stderr": "",
            }
        return {"returncode": 0, "stdout": "", "stderr": ""}

    result = task_194_runtime.capture_lineage(tmp_path, runner=runner)

    unit_commands = [
        command for command in commands
        if list(command[:2]) == ["systemctl", "show"]
    ]
    assert unit_commands
    assert unit_commands[0][2] == "marcedit-web-private.service"
    assert any(
        command[0] == "/opt/marcedit/.venv/bin/python"
        for command in commands
    )
    assert result["units"]["selected_unit"] == "marcedit-web-private.service"


def test_capture_lineage_reports_incomplete_evidence(tmp_path):
    def runner(command):
        return {"returncode": 1, "stdout": "", "stderr": "unavailable"}

    result = task_194_runtime.capture_lineage(tmp_path, runner=runner)

    assert result["complete"] is False
    assert result["capture_errors"]


def test_runtime_capture_cli_imports_from_a_checkout_without_pythonpath():
    script = Path(__file__).parents[1] / "scripts" / "capture_task_194_runtime_lineage.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        ["python3", str(script), "--help"],
        cwd=script.parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
