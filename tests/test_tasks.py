"""Tests for marcedit_web.lib.tasks (the @task registry)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import tasks


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Each test runs against a clean registry."""
    saved = dict(tasks.TASK_REGISTRY)
    saved_names = {k: set(v) for k, v in tasks._MODULE_TASK_NAMES.items()}
    saved_mtimes = dict(tasks._MODULE_LOAD_MTIMES)
    tasks.TASK_REGISTRY.clear()
    tasks._MODULE_TASK_NAMES.clear()
    tasks._MODULE_LOAD_MTIMES.clear()
    yield
    tasks.TASK_REGISTRY.clear()
    tasks.TASK_REGISTRY.update(saved)
    tasks._MODULE_TASK_NAMES.clear()
    tasks._MODULE_TASK_NAMES.update(saved_names)
    tasks._MODULE_LOAD_MTIMES.clear()
    tasks._MODULE_LOAD_MTIMES.update(saved_mtimes)


def test_task_decorator_registers_function():
    @tasks.task("my-task", description="Test task")
    def fn(record):
        pass

    assert "my-task" in tasks.TASK_REGISTRY
    entry = tasks.TASK_REGISTRY["my-task"]
    assert entry.name == "my-task"
    assert entry.description == "Test task"
    assert entry.fn is fn


def test_get_returns_none_for_missing():
    assert tasks.get("not-registered") is None


def test_all_tasks_sorted_by_name():
    @tasks.task("zeta")
    def _z(r):
        pass

    @tasks.task("alpha")
    def _a(r):
        pass

    names = [t.name for t in tasks.all_tasks()]
    assert names == ["alpha", "zeta"]


def test_load_user_tasks_imports_py_files(tmp_path):
    p = tmp_path / "my_task.py"
    p.write_text(
        '"""doc"""\n'
        "from marcedit_web.lib.tasks import task\n"
        "\n"
        "@task('hello', description='Greet')\n"
        "def hello(record):\n"
        "    pass\n"
    )
    loaded = tasks.load_user_tasks(tmp_path)
    assert loaded == 1
    assert "hello" in tasks.TASK_REGISTRY


def test_load_user_tasks_skips_underscore_prefix(tmp_path):
    (tmp_path / "_private.py").write_text("")
    assert tasks.load_user_tasks(tmp_path) == 0


def test_load_user_tasks_records_syntax_errors(tmp_path):
    (tmp_path / "broken.py").write_text("this is not python )")
    assert tasks.load_user_tasks(tmp_path) == 0
    assert tasks.LAST_LOAD_ISSUES
    assert tasks.LAST_LOAD_ISSUES[0].code == "task-load-failed"


def test_auto_load_shipped_tasks_is_gone():
    assert not hasattr(tasks, "_auto_load_shipped_tasks")
