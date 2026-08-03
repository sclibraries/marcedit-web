"""Read-only runtime-lineage capture contract for TASK-194."""

from pathlib import Path

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
