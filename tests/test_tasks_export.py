"""Tests for Tasks-page export naming (TASK-141)."""

from __future__ import annotations

import re
import sys
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
        self.buttons: list[dict] = []
        self.captions: list[str] = []
        self.download_buttons: list[dict] = []
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.markdowns: list[str] = []
        self.metrics: list[tuple[str, object]] = []

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

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return False

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


def test_history_location_caption_points_to_job_snapshots_when_available():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(7) == (
        "Rollback and before/after downloads are available under Job snapshots "
        "on this Tasks page."
    )


def test_history_location_caption_explains_unsigned_fallback():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(None) == (
        "Rollback history is only available for signed-in job files. "
        "Download the updated MARC file below."
    )


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
