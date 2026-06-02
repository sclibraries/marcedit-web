"""Tests for the file → SQL task migration (TASK-050).

Covers ``db._migrate_v1_to_v2`` invoked transparently by
``db.init_schema`` when the stored schema version is < 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from marcedit_web.lib import db, editor, task_db


def _seed_user_task(tasks_root: Path, user_slug: str, name: str, description: str = "") -> Path:
    """Drop a task file into ``data/tasks/users/<slug>/`` shape."""
    dir_ = tasks_root / "users" / user_slug
    dir_.mkdir(parents=True, exist_ok=True)
    return _write_task_file(dir_, name, description)


def _seed_shared_task(tasks_root: Path, name: str, description: str = "") -> Path:
    dir_ = tasks_root / "shared"
    dir_.mkdir(parents=True, exist_ok=True)
    return _write_task_file(dir_, name, description)


def _write_task_file(dir_: Path, name: str, description: str) -> Path:
    content = editor.serialize_user_task(name, description, "pass\n")
    path = editor.task_file_path(dir_, name)
    path.write_text(content)
    return path


def test_migration_imports_user_tasks(tmp_path, monkeypatch):
    tasks_root = tmp_path / "tasks"
    monkeypatch.setenv("MARCEDIT_WEB_TASKS_ROOT", str(tasks_root))
    _seed_user_task(tasks_root, "alice@example.edu", "strip-029", "drop 029")
    _seed_user_task(tasks_root, "alice@example.edu", "fix-leader")
    _seed_user_task(tasks_root, "bob@example.edu", "bob-only")

    db.reset_for_tests()
    db.init_schema()

    alice = task_db.list_own_tasks("alice@example.edu")
    bob = task_db.list_own_tasks("bob@example.edu")
    assert {t["name"] for t in alice} == {"strip-029", "fix-leader"}
    assert {t["name"] for t in bob} == {"bob-only"}
    assert all(t["visibility"] == "private" for t in alice + bob)


def test_migration_imports_shared_tasks_under_sentinel(tmp_path, monkeypatch):
    tasks_root = tmp_path / "tasks"
    monkeypatch.setenv("MARCEDIT_WEB_TASKS_ROOT", str(tasks_root))
    _seed_shared_task(tasks_root, "global-cleanup", "shared library task")

    db.reset_for_tests()
    db.init_schema()

    shared = task_db.list_own_tasks(db.SHARED_OWNER_SENTINEL)
    assert len(shared) == 1
    assert shared[0]["name"] == "global-cleanup"
    assert shared[0]["visibility"] == "shared"


def test_migration_makes_shared_visible_to_arbitrary_user(tmp_path, monkeypatch):
    tasks_root = tmp_path / "tasks"
    monkeypatch.setenv("MARCEDIT_WEB_TASKS_ROOT", str(tasks_root))
    _seed_shared_task(tasks_root, "shared-task")

    db.reset_for_tests()
    db.init_schema()

    visible_to_alice = {
        t["name"] for t in task_db.list_visible_tasks("alice@example.edu")
    }
    assert "shared-task" in visible_to_alice


def test_migration_idempotent_no_duplicate_rows(tmp_path, monkeypatch):
    tasks_root = tmp_path / "tasks"
    monkeypatch.setenv("MARCEDIT_WEB_TASKS_ROOT", str(tasks_root))
    _seed_user_task(tasks_root, "alice@example.edu", "t1")

    db.reset_for_tests()
    db.init_schema()
    db.reset_for_tests()
    db.init_schema()  # second pass

    rows = task_db.list_own_tasks("alice@example.edu")
    assert len(rows) == 1


def test_migration_bumps_schema_version(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MARCEDIT_WEB_TASKS_ROOT", str(tmp_path / "empty-tasks"),
    )
    db.reset_for_tests()
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute("SELECT version FROM _schema_version").fetchone()
    assert row["version"] == db.SCHEMA_VERSION


def test_migration_skips_unparseable_files(tmp_path, monkeypatch, caplog):
    tasks_root = tmp_path / "tasks"
    monkeypatch.setenv("MARCEDIT_WEB_TASKS_ROOT", str(tasks_root))
    # One valid + one broken.
    _seed_user_task(tasks_root, "alice@example.edu", "good")
    bad_dir = tasks_root / "users" / "alice@example.edu"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "broken.py").write_text("not python (")

    db.reset_for_tests()
    with caplog.at_level("WARNING", logger="marcedit_web.db"):
        db.init_schema()

    rows = task_db.list_own_tasks("alice@example.edu")
    assert {r["name"] for r in rows} == {"good"}
    assert any("skipping unparseable" in m for m in caplog.messages)


def test_migration_runs_even_when_no_tasks_root_exists(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MARCEDIT_WEB_TASKS_ROOT", str(tmp_path / "does-not-exist"),
    )
    db.reset_for_tests()
    db.init_schema()  # must not raise
    with db.connect() as conn:
        row = conn.execute("SELECT version FROM _schema_version").fetchone()
    assert row["version"] == db.SCHEMA_VERSION
