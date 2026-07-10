"""Tasks page mode switcher (TASK-143).

The page previously stacked authoring, running, results, history, and
quick tools in one scroll. These tests pin the new contract: exactly
one mode renders per run, the selection survives reruns via
session_state, and opening the editor forces Build & import so the
editor is never rendered invisibly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.radios: list[dict] = []
        self.dividers = 0

    def radio(self, label, options, horizontal=False, key=None,
              label_visibility=None):
        self.radios.append(
            {"label": label, "options": tuple(options), "key": key}
        )
        value = self.session_state.get(key)
        if value is None:
            value = options[0]
            self.session_state[key] = value
        return value

    def divider(self):
        self.dividers += 1


def _tasks_render(monkeypatch, fake_st):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    return tasks_render


def _wire(monkeypatch, tasks_render, calls):
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.task_admin, "is_admin", lambda user: False
    )
    monkeypatch.setattr(
        tasks_render, "_refresh_tasks_for", lambda user: Path("/tmp/tasks")
    )
    monkeypatch.setattr(
        tasks_render.tasks,
        "load_user_tasks",
        lambda d, force_reload=False: None,
    )
    monkeypatch.setattr(tasks_render.tasks, "all_tasks", lambda: {})
    monkeypatch.setattr(tasks_render, "loaded_batch_status", lambda: None)
    monkeypatch.setattr(
        tasks_render, "_render_run_mode",
        lambda registered, tasks_dir: calls.append("run"),
    )
    monkeypatch.setattr(
        tasks_render, "_render_quick_ops_mode",
        lambda: calls.append("quick"),
    )
    monkeypatch.setattr(
        tasks_render, "_render_build_mode",
        lambda *args: calls.append("build"),
    )


def test_default_mode_is_run_and_only_run(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)

    tasks_render.render()

    assert calls == ["run"]
    assert fake_st.session_state[tasks_render.K_MODE_WIDGET] == (
        tasks_render.MODE_RUN
    )


def test_mode_selection_survives_rerun(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)
    fake_st.session_state[tasks_render.K_MODE_WIDGET] = (
        tasks_render.MODE_QUICK
    )

    tasks_render.render()

    assert calls == ["quick"]


def test_force_mode_overrides_and_clears(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)
    fake_st.session_state[tasks_render.K_MODE_WIDGET] = (
        tasks_render.MODE_RUN
    )
    fake_st.session_state[tasks_render.K_FORCE_MODE] = (
        tasks_render.MODE_BUILD
    )

    tasks_render.render()

    assert calls == ["build"]
    assert tasks_render.K_FORCE_MODE not in fake_st.session_state
    assert fake_st.session_state[tasks_render.K_MODE_WIDGET] == (
        tasks_render.MODE_BUILD
    )


def test_open_editor_for_new_forces_build_mode(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)

    tasks_render._open_editor_for_new()

    assert fake_st.session_state[tasks_render.K_FORCE_MODE] == (
        tasks_render.MODE_BUILD
    )
