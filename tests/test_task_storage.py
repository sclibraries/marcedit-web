"""Tests for marcedit_web.lib.task_storage."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from marcedit_web.lib import editor, task_storage, tasks


@pytest.fixture
def tasks_root(tmp_path, monkeypatch) -> Path:
    """Point the tasks root at a per-test tmp dir."""
    root = tmp_path / "data" / "tasks"
    monkeypatch.setenv("MARCEDIT_WEB_TASKS_ROOT", str(root))
    return root


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Each test starts from a clean task registry."""
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


# ---------------------------------------------------------------------------
# Slug safety
# ---------------------------------------------------------------------------


def test_safe_user_slug_passthrough_for_email_like():
    assert task_storage.safe_user_slug("rconnell@smith.edu") == "rconnell@smith.edu"


def test_safe_user_slug_anonymous_for_empty():
    assert task_storage.safe_user_slug("") == "anonymous"
    assert task_storage.safe_user_slug(None) == "anonymous"  # type: ignore[arg-type]


def test_safe_user_slug_blocks_path_traversal():
    slug = task_storage.safe_user_slug("../../etc/passwd")
    assert "/" not in slug
    assert ".." not in slug


def test_safe_user_slug_replaces_other_specials():
    slug = task_storage.safe_user_slug("user name; rm -rf /")
    assert " " not in slug
    assert ";" not in slug
    assert "/" not in slug


# ---------------------------------------------------------------------------
# Tasks root override
# ---------------------------------------------------------------------------


def test_tasks_root_env_override(tasks_root):
    assert task_storage.tasks_root() == tasks_root


def test_tasks_root_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_TASKS_ROOT", raising=False)
    root = task_storage.tasks_root()
    assert root.name == "tasks"
    assert root.parent.name == "data"


# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------


def test_user_tasks_dir_creates_lazily(tasks_root):
    p = task_storage.user_tasks_dir("rconnell@smith.edu")
    assert p.exists()
    assert p.parent.name == "users"
    assert p.parent.parent == tasks_root


def test_shared_tasks_dir_creates_lazily(tasks_root):
    p = task_storage.shared_tasks_dir()
    assert p.exists()
    assert p.name == "shared"
    assert p.parent == tasks_root


def test_visible_task_dirs_returns_shared_then_user(tasks_root):
    dirs = task_storage.visible_task_dirs("eppn@example.edu")
    assert len(dirs) == 2
    assert dirs[0] == task_storage.shared_tasks_dir()
    assert dirs[1] == task_storage.user_tasks_dir("eppn@example.edu")


# ---------------------------------------------------------------------------
# Round-trip + shadowing via editor + tasks loader
# ---------------------------------------------------------------------------


def test_task_round_trip_via_user_dir(tasks_root):
    user_dir = task_storage.user_tasks_dir("eppn@example.edu")
    editor.save_user_task(
        user_dir,
        name="hello",
        description="Greet",
        body="pass",
    )
    tasks.load_user_tasks(user_dir)
    assert "hello" in tasks.TASK_REGISTRY


def test_user_task_shadows_shared(tasks_root):
    # Write a "hello" task into shared with description "shared-version".
    shared = task_storage.shared_tasks_dir()
    editor.save_user_task(
        shared, name="hello", description="shared-version", body="pass",
    )
    # And a different "hello" into a user dir.
    user_dir = task_storage.user_tasks_dir("eppn@example.edu")
    editor.save_user_task(
        user_dir, name="hello", description="user-version", body="pass",
    )
    # Load in the documented order: shared first, user second.
    for d in task_storage.visible_task_dirs("eppn@example.edu"):
        tasks.load_user_tasks(d, force_reload=True)
    # User's version wins because it loaded last and re-registered.
    assert tasks.TASK_REGISTRY["hello"].description == "user-version"


def test_evil_eppn_cannot_escape_users_dir(tasks_root):
    p = task_storage.user_tasks_dir("../../../etc/passwd")
    # Resolved path must remain UNDER the users/ root.
    users_root = (tasks_root / "users").resolve()
    assert str(p.resolve()).startswith(str(users_root))
