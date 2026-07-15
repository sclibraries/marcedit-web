"""Tests for Tasks-page export naming (TASK-141)."""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from types import SimpleNamespace


class _Spinner:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _tasks_render():
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    return tasks_render


class _FakeColumn:
    def __init__(self, st):
        self._st = st

    def metric(self, label, value):
        self._st.metrics.append((label, value))

    def button(self, label, **kwargs):
        self._st.buttons.append({"label": label, **kwargs})
        return False

    def download_button(self, **kwargs):
        self._st.download_buttons.append(kwargs)

    def caption(self, message):
        self._st.captions.append(str(message))


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.clicked_keys: set[str] = set()
        self.buttons: list[dict] = []
        self.captions: list[str] = []
        self.download_buttons: list[dict] = []
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.markdowns: list[str] = []
        self.metrics: list[tuple[str, object]] = []
        self.successes: list[str] = []

    def divider(self):
        pass

    def markdown(self, message):
        self.markdowns.append(str(message))

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn(self) for _ in range(count)]

    def caption(self, message):
        self.captions.append(str(message))

    def info(self, message):
        self.infos.append(str(message))

    def error(self, message):
        self.errors.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return kwargs.get("key") in self.clicked_keys

    def download_button(self, **kwargs):
        self.download_buttons.append(kwargs)

    def spinner(self, _message):
        return _Spinner()


def test_export_filename_keeps_source_name_but_adds_operation_suffix():
    tasks_render = _tasks_render()

    filename = tasks_render._export_filename("source-file.mrc", "tasks")

    assert filename != "source-file.mrc"
    assert re.fullmatch(r"source-file_tasks_\d{8}_\d{6}\.mrc", filename)


def test_export_filename_defaults_when_source_missing():
    tasks_render = _tasks_render()

    filename = tasks_render._export_filename(None, "quickbatch")

    assert re.fullmatch(r"transformed_quickbatch_\d{8}_\d{6}\.mrc", filename)


def test_history_location_caption_points_to_history_page_when_available():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(7) == (
        "Rollback and before/after downloads are available on the "
        "History page."
    )


def test_history_location_caption_explains_unsigned_fallback():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(None) == (
        "Rollback history is only available for signed-in job files. "
        "Download the updated MARC file below."
    )


def test_batch_operation_uses_shared_gate_and_telemetry(monkeypatch, tmp_path):
    tasks_render = _tasks_render()
    source_path = tmp_path / "source.mrc"
    source_path.write_bytes(b"batch-bytes")
    store = SimpleNamespace(count=lambda: 100_000, path=source_path)
    events = []

    @contextmanager
    def _slot(operation):
        events.append(("slot", operation))
        yield

    @contextmanager
    def _measure(operation, **dimensions):
        events.append(("measure", operation, dimensions))
        yield

    monkeypatch.setattr(tasks_render.batch_runtime, "batch_slot", _slot)
    monkeypatch.setattr(
        tasks_render.batch_runtime, "measure_operation", _measure
    )

    with tasks_render._batch_operation(
        "quick-batch", phase="preview", store=store
    ):
        events.append(("body",))

    assert events == [
        ("slot", "quick-batch"),
        (
            "measure",
            "quick-batch",
            {
                "phase": "preview",
                "records": 100_000,
                "bytes": len(b"batch-bytes"),
            },
        ),
        ("body",),
    ]


def test_render_run_results_uses_output_path_without_session_bytes(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    input_path = tmp_path / "input.mrc"
    output_path = tmp_path / "output.mrc"
    input_path.write_bytes(b"input")
    output_path.write_bytes(b"output")
    fake_st.session_state[tasks_render.K_RUN_RESULTS] = {
        "issues": [],
        "out_filename": "source_tasks_20260709_190000.mrc",
        "out_path": str(output_path),
        "input_count": 1,
        "output_count": 1,
        "ran_tasks": ["Leader cleanup"],
        "timed_out": False,
        "sandbox_returncode": 0,
        "sandbox_input_path": str(input_path),
        "_diff_summary": tasks_render.task_diff.TaskDiffSummary(
            total_in=1,
            total_out=1,
            changed_count=0,
            unchanged_count=1,
        ),
        "snapshot_id": None,
    }

    tasks_render._render_run_results()

    assert "out_bytes" not in fake_st.session_state[tasks_render.K_RUN_RESULTS]
    assert fake_st.download_buttons == []
    assert fake_st.buttons == [
        {
            "label": "Prepare Download source_tasks_20260709_190000.mrc",
            "key": "tasks_download_prepare",
            "help": (
                "Loads the file from disk and offers a download button. "
                "Two-step gate avoids re-reading large historical files "
                "on every page refresh."
            ),
        }
    ]


def test_render_run_results_does_not_read_output_when_diff_summary_missing(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    monkeypatch.setattr(
        tasks_render.task_diff,
        "compute_task_diff",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("diff should not rebuild during render")
        ),
    )
    input_path = tmp_path / "input.mrc"
    output_path = tmp_path / "output.mrc"
    input_path.write_bytes(b"input")
    output_path.write_bytes(b"output")
    fake_st.session_state[tasks_render.K_RUN_RESULTS] = {
        "issues": [],
        "out_filename": "source_tasks_20260709_190000.mrc",
        "out_path": str(output_path),
        "input_count": 1,
        "output_count": 1,
        "ran_tasks": ["Leader cleanup"],
        "timed_out": True,
        "sandbox_returncode": 124,
        "sandbox_input_path": str(input_path),
        "_diff_summary": None,
        "snapshot_id": None,
    }

    tasks_render._render_run_results()

    assert fake_st.download_buttons == []
    assert fake_st.buttons[0]["label"] == (
        "Prepare Download source_tasks_20260709_190000.mrc"
    )


def test_saved_task_output_requires_explicit_version_adoption(
    monkeypatch, tmp_path,
):
    """A successful run is reviewable output until the cataloger accepts it."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    output_path = tmp_path / "output.mrc"
    input_path = tmp_path / "input.mrc"
    output_path.write_bytes(b"output")
    input_path.write_bytes(b"input")
    results = {
        "issues": [],
        "out_filename": "source_tasks.mrc",
        "out_path": str(output_path),
        "input_count": 1,
        "output_count": 1,
        "error_count": 0,
        "ran_tasks": ["Leader cleanup"],
        "timed_out": False,
        "sandbox_returncode": 0,
        "sandbox_input_path": str(input_path),
        "_diff_summary": None,
        "snapshot_id": None,
        "task_label": "Leader cleanup",
        "summary": {"changed_count": 1},
        "validation": {"error_count": 0},
        "preview_version_id": 21,
    }
    fake_st.session_state.update({
        tasks_render.K_RUN_RESULTS: results,
        "job_file_id": 9,
        "job_file_version_id": 21,
    })
    adopted = []
    monkeypatch.setattr(
        tasks_render.session,
        "adopt_current_candidate",
        lambda **kwargs: adopted.append({
            **kwargs,
            "candidate_bytes": kwargs["candidate_path"].read_bytes(),
        }) or {"version_number": 2},
    )

    tasks_render._render_run_results()

    assert adopted == []
    assert any(button["label"] == "Apply as new version" for button in fake_st.buttons)
    assert fake_st.session_state[tasks_render.K_RUN_RESULTS] is results

    fake_st.clicked_keys.add("task_apply_version")
    tasks_render._render_run_results()

    assert adopted[0]["candidate_path"] != output_path
    assert adopted[0]["candidate_bytes"] == b"output"
    assert adopted[0]["source_kind"] == "task"
    assert adopted[0]["label"] == "Leader cleanup"
    assert adopted[0]["summary"] == {"changed_count": 1}
    assert adopted[0]["validation"] == {"error_count": 0}
    assert tasks_render.K_RUN_RESULTS not in fake_st.session_state


def test_saved_task_output_rejects_a_newer_opened_version(monkeypatch, tmp_path):
    """An old preview must not overwrite work accepted later in the session."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    output_path = tmp_path / "output.mrc"
    output_path.write_bytes(b"preview")
    fake_st.session_state.update({
        tasks_render.K_RUN_RESULTS: {
            "issues": [],
            "out_filename": "tasks.mrc",
            "out_path": str(output_path),
            "input_count": 1,
            "output_count": 1,
            "error_count": 0,
            "ran_tasks": ["Cleanup"],
            "timed_out": False,
            "sandbox_returncode": 0,
            "sandbox_input_path": None,
            "_diff_summary": None,
            "snapshot_id": None,
            "task_label": "Cleanup",
            "summary": {},
            "validation": {},
            "preview_version_id": 20,
        },
        "job_file_id": 9,
        "job_file_version_id": 21,
    })
    fake_st.clicked_keys.add("task_apply_version")
    monkeypatch.setattr(
        tasks_render.session,
        "adopt_current_candidate",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("stale preview must not reach adoption")
        ),
    )

    tasks_render._render_run_results()

    assert fake_st.errors == [
        "File changed since this task output was previewed. Run the task again."
    ]
    assert output_path.exists()
