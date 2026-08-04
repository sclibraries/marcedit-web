"""Characterization tests for the TASK-194 synchronous task path."""

from pathlib import Path

from marcedit_web.lib import sandbox, synchronous_task_runner


def test_run_tasks_uses_sandbox_without_operation_submission(tmp_path, monkeypatch):
    input_path = tmp_path / "input.mrc"
    input_path.write_bytes(b"source")
    output_path = tmp_path / "output.mrc"
    calls = []

    def fake_run(specs, *, input_path, tmp_dir):
        calls.append((list(specs), input_path, tmp_dir))
        output_path.write_bytes(b"result")
        return sandbox.SandboxResult(output_path=output_path, errors=[])

    monkeypatch.setattr(sandbox, "run_tasks_subprocess", fake_run)

    result = synchronous_task_runner.run_tasks(
        input_path,
        [sandbox.TaskSpec(name="cleanup", body="pass\n")],
        tmp_dir=tmp_path / "work",
    )

    assert result.output_path == output_path
    assert result.input_path == input_path
    assert calls[0][0][0].name == "cleanup"
    assert calls[0][1] == input_path
    assert calls[0][2] == tmp_path / "work"


def test_run_tasks_rejects_missing_input_before_child_start(tmp_path):
    missing = tmp_path / "missing.mrc"

    try:
        synchronous_task_runner.run_tasks(
            missing,
            [sandbox.TaskSpec(name="cleanup", body="pass\n")],
        )
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing input must fail before sandbox execution")


def test_tasks_run_panel_is_sync_only():
    source = Path("marcedit_web/render/tasks.py").read_text()
    start = source.index("def _render_run_panel")
    end = source.index("def _execute_synchronous_run", start)
    source = source[start:end]
    assert "_execute_synchronous_run" in source
    assert "_submit_queued_run" not in source
