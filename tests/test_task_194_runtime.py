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
                    "Environment=MARCEDIT_WEB_DB_PATH=/opt/marcedit/data/production.db\n"
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
    database_commands = [
        command for command in commands
        if command[:2] == ("/opt/marcedit/.venv/bin/python", "-c")
        and "production.db" in command[2]
    ]
    assert database_commands
    assert result["units"]["selected_unit"] == "marcedit-web-private.service"


def test_capture_lineage_does_not_infer_python_when_execstart_is_unparseable(
    tmp_path,
):
    commands = []

    def runner(command):
        commands.append(tuple(command))
        if list(command[:3]) == [
            "systemctl", "list-unit-files", "marcedit-web*.service"
        ]:
            return {
                "returncode": 0,
                "stdout": "marcedit-web.service enabled\n",
                "stderr": "",
            }
        if list(command[:2]) == ["systemctl", "show"]:
            return {
                "returncode": 0,
                "stdout": (
                    "ActiveState=active\n"
                    "WorkingDirectory=" + str(tmp_path) + "\n"
                    "ExecStart=not-a-systemd-executable\n"
                ),
                "stderr": "",
            }
        return {"returncode": 0, "stdout": "captured", "stderr": ""}

    result = task_194_runtime.capture_lineage(tmp_path, runner=runner)

    assert result["complete"] is False
    assert result["dependencies"]["python"]["status"] == "failed"
    assert not any(
        command and command[0] == str(tmp_path / ".venv" / "bin" / "python")
        for command in commands
    )


def test_capture_lineage_reports_selected_unit_capture_failure(tmp_path):
    def runner(command):
        if list(command[:3]) == [
            "systemctl", "list-unit-files", "marcedit-web*.service"
        ]:
            return {
                "returncode": 0,
                "stdout": "marcedit-web.service enabled\n",
                "stderr": "",
            }
        if list(command[:2]) == ["systemctl", "show"]:
            return {
                "returncode": 1,
                "stdout": (
                    "ActiveState=active\n"
                    "WorkingDirectory=" + str(tmp_path) + "\n"
                    "ExecStart={ path="
                    + str(tmp_path / ".venv" / "bin" / "streamlit")
                    + " }\n"
                ),
                "stderr": "systemd query failed",
            }
        return {"returncode": 0, "stdout": "captured", "stderr": ""}

    result = task_194_runtime.capture_lineage(tmp_path, runner=runner)

    assert result["complete"] is False
    assert any(
        item.startswith("unit:") for item in result["capture_errors"]
    )


def test_capture_lineage_refuses_to_choose_between_multiple_active_units(tmp_path):
    def runner(command):
        if list(command[:3]) == [
            "systemctl", "list-unit-files", "marcedit-web*.service"
        ]:
            return {
                "returncode": 0,
                "stdout": (
                    "marcedit-web-private.service enabled\n"
                    "marcedit-web-public.service enabled\n"
                ),
                "stderr": "",
            }
        if list(command[:2]) == ["systemctl", "show"]:
            return {
                "returncode": 0,
                "stdout": "ActiveState=active\n",
                "stderr": "",
            }
        return {"returncode": 0, "stdout": "", "stderr": ""}

    result = task_194_runtime.capture_lineage(tmp_path, runner=runner)

    assert result["units"]["selected_unit"] is None
    assert "active_unit_ambiguous" in result["capture_errors"]
    assert result["complete"] is False


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
