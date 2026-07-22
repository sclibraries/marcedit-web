"""Tests for marcedit_web.lib.task_db (TASK-050)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import db, editor, task_db


@pytest.fixture(autouse=True)
def _schema():
    """Make sure the v2 schema is present before every test."""
    db.init_schema()


def _save(owner, name, *, body="pass\n", description="", visibility="private"):
    task_db.save_task(
        owner=owner,
        name=name,
        description=description,
        body=body,
        visibility=visibility,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_round_trip():
    _save("alice@example.edu", "strip-029", description="Drop 029 fields")
    row = task_db.get_task("alice@example.edu", "strip-029")
    assert row is not None
    assert row["owner_email"] == "alice@example.edu"
    assert row["name"] == "strip-029"
    assert row["description"] == "Drop 029 fields"
    assert row["visibility"] == "private"
    assert row["created_at"] == row["updated_at"]


def test_get_returns_none_for_missing():
    assert task_db.get_task("alice@example.edu", "nope") is None


def test_save_updates_existing_row():
    _save("alice@example.edu", "t1", description="v1")
    before = task_db.get_task("alice@example.edu", "t1")
    _save("alice@example.edu", "t1", description="v2")
    after = task_db.get_task("alice@example.edu", "t1")
    assert before["id"] == after["id"]  # same row
    assert after["description"] == "v2"


def test_delete_returns_true_when_found():
    _save("alice@example.edu", "t1")
    assert task_db.delete_task("alice@example.edu", "t1") is True
    assert task_db.get_task("alice@example.edu", "t1") is None


def test_delete_returns_false_when_missing():
    assert task_db.delete_task("alice@example.edu", "nope") is False


def test_invalid_name_rejected():
    with pytest.raises(ValueError, match="invalid task name"):
        _save("alice@example.edu", "Has Spaces")


def test_invalid_visibility_rejected():
    with pytest.raises(ValueError, match="invalid visibility"):
        _save("alice@example.edu", "t1", visibility="public")


def test_set_visibility_toggle():
    _save("alice@example.edu", "t1", visibility="private")
    task_db.set_visibility("alice@example.edu", "t1", "shared")
    assert task_db.get_task("alice@example.edu", "t1")["visibility"] == "shared"
    task_db.set_visibility("alice@example.edu", "t1", "private")
    assert task_db.get_task("alice@example.edu", "t1")["visibility"] == "private"


# ---------------------------------------------------------------------------
# Shared-task collaborator updates
# ---------------------------------------------------------------------------


def test_update_shared_task_preserves_identity_and_visibility():
    _save(
        "owner@example.edu",
        "cleanup",
        body="old\n",
        description="old",
        visibility="shared",
    )
    before = task_db.get_task("owner@example.edu", "cleanup")

    task_db.update_shared_task(
        actor="editor@example.edu",
        owner="owner@example.edu",
        name="cleanup",
        description="corrected",
        body="new\n",
        extra_imports=[
            "from marcedit_web.lib.transforms import delete_tags",
        ],
        expected=task_db.task_edit_snapshot(before),
    )

    after = task_db.get_task("owner@example.edu", "cleanup")
    assert after["id"] == before["id"]
    assert after["owner_email"] == "owner@example.edu"
    assert after["name"] == "cleanup"
    assert after["visibility"] == "shared"
    assert after["created_at"] == before["created_at"]
    assert after["description"] == "corrected"
    assert after["body"] == "new\n"
    assert after["extra_imports"] == (
        "from marcedit_web.lib.transforms import delete_tags"
    )


def test_update_shared_task_rejects_same_second_stale_snapshot(monkeypatch):
    monkeypatch.setattr(task_db, "_utc_now", lambda: "2026-07-22T12:00:00Z")
    _save("owner@example.edu", "cleanup", body="opened\n", visibility="shared")
    opened = task_db.get_task("owner@example.edu", "cleanup")
    _save("owner@example.edu", "cleanup", body="newer\n", visibility="shared")

    with pytest.raises(ValueError, match="changed since you opened"):
        task_db.update_shared_task(
            actor="editor@example.edu",
            owner="owner@example.edu",
            name="cleanup",
            description="stale",
            body="stale\n",
            extra_imports=None,
            expected=task_db.task_edit_snapshot(opened),
        )

    assert task_db.get_task("owner@example.edu", "cleanup")["body"] == "newer\n"


def test_update_shared_task_rejects_private_task_without_changing_it():
    _save("owner@example.edu", "cleanup", body="private\n", visibility="private")
    before = task_db.get_task("owner@example.edu", "cleanup")

    with pytest.raises(ValueError, match="no longer shared"):
        task_db.update_shared_task(
            actor="editor@example.edu",
            owner="owner@example.edu",
            name="cleanup",
            description="changed",
            body="changed\n",
            extra_imports=None,
            expected=task_db.task_edit_snapshot(before),
        )

    assert task_db.get_task("owner@example.edu", "cleanup") == before


def test_update_shared_task_rejects_task_unshared_after_opening():
    _save("owner@example.edu", "cleanup", body="shared\n", visibility="shared")
    opened = task_db.get_task("owner@example.edu", "cleanup")
    task_db.set_visibility("owner@example.edu", "cleanup", "private")
    before_attempt = task_db.get_task("owner@example.edu", "cleanup")

    with pytest.raises(ValueError, match="no longer shared"):
        task_db.update_shared_task(
            actor="editor@example.edu",
            owner="owner@example.edu",
            name="cleanup",
            description="changed",
            body="changed\n",
            extra_imports=None,
            expected=task_db.task_edit_snapshot(opened),
        )

    assert task_db.get_task("owner@example.edu", "cleanup") == before_attempt


def test_update_shared_task_rejects_deleted_task():
    _save("owner@example.edu", "cleanup", visibility="shared")
    opened = task_db.get_task("owner@example.edu", "cleanup")
    task_db.delete_task("owner@example.edu", "cleanup")

    with pytest.raises(ValueError, match="was removed"):
        task_db.update_shared_task(
            actor="editor@example.edu",
            owner="owner@example.edu",
            name="cleanup",
            description="changed",
            body="changed\n",
            extra_imports=None,
            expected=task_db.task_edit_snapshot(opened),
        )

    assert task_db.get_task("owner@example.edu", "cleanup") is None


def test_update_shared_task_rejects_blank_actor_without_changing_task():
    _save("owner@example.edu", "cleanup", visibility="shared")
    before = task_db.get_task("owner@example.edu", "cleanup")

    with pytest.raises(ValueError, match="signed-in cataloger required"):
        task_db.update_shared_task(
            actor="",
            owner="owner@example.edu",
            name="cleanup",
            description="changed",
            body="changed\n",
            extra_imports=None,
            expected=task_db.task_edit_snapshot(before),
        )

    assert task_db.get_task("owner@example.edu", "cleanup") == before


def test_update_shared_task_rejects_owner_without_changing_task():
    _save("owner@example.edu", "cleanup", visibility="shared")
    before = task_db.get_task("owner@example.edu", "cleanup")

    with pytest.raises(ValueError, match="owner must use the owner save path"):
        task_db.update_shared_task(
            actor="owner@example.edu",
            owner="owner@example.edu",
            name="cleanup",
            description="changed",
            body="changed\n",
            extra_imports=None,
            expected=task_db.task_edit_snapshot(before),
        )

    assert task_db.get_task("owner@example.edu", "cleanup") == before


# ---------------------------------------------------------------------------
# Visibility filter — the security-relevant slice
# ---------------------------------------------------------------------------


def test_list_visible_excludes_other_users_private_tasks():
    _save("alice@example.edu", "alice-private", visibility="private")
    _save("bob@example.edu", "bob-private", visibility="private")
    visible_to_alice = task_db.list_visible_tasks("alice@example.edu")
    names = {t["name"] for t in visible_to_alice}
    assert "alice-private" in names
    assert "bob-private" not in names


def test_list_visible_includes_other_users_shared_tasks():
    _save("alice@example.edu", "alice-only", visibility="private")
    _save("bob@example.edu", "bob-public", visibility="shared")
    names = {t["name"] for t in task_db.list_visible_tasks("alice@example.edu")}
    assert names == {"alice-only", "bob-public"}


def test_list_visible_includes_users_own_shared_tasks():
    _save("alice@example.edu", "alice-public", visibility="shared")
    names = {t["name"] for t in task_db.list_visible_tasks("alice@example.edu")}
    assert names == {"alice-public"}


def test_list_own_returns_only_owned_regardless_of_visibility():
    _save("alice@example.edu", "p", visibility="private")
    _save("alice@example.edu", "s", visibility="shared")
    _save("bob@example.edu", "b", visibility="shared")
    own = {t["name"] for t in task_db.list_own_tasks("alice@example.edu")}
    assert own == {"p", "s"}


def test_count_visible_separates_own_from_shared_from_others():
    _save("alice@example.edu", "p1", visibility="private")
    _save("alice@example.edu", "p2", visibility="private")
    _save("alice@example.edu", "s1", visibility="shared")
    _save("bob@example.edu", "bs", visibility="shared")
    _save("bob@example.edu", "bp", visibility="private")
    counts = task_db.count_visible("alice@example.edu")
    assert counts == {"own": 3, "shared_from_others": 1}


def test_unique_constraint_per_owner():
    # Same name owned by two different users is allowed.
    _save("alice@example.edu", "t1")
    _save("bob@example.edu", "t1")
    assert (
        task_db.get_task("alice@example.edu", "t1")["id"]
        != task_db.get_task("bob@example.edu", "t1")["id"]
    )


# ---------------------------------------------------------------------------
# Materialization to disk (for the Python loader contract)
# ---------------------------------------------------------------------------


def test_materialize_to_dir_writes_visible_tasks(tmp_path):
    _save("alice@example.edu", "alice-own", description="A's task", body="pass\n")
    _save("bob@example.edu", "bob-shared", visibility="shared", body="pass\n")
    _save("bob@example.edu", "bob-private", visibility="private")

    target = tmp_path / "mat"
    count = task_db.materialize_to_dir("alice@example.edu", target)
    assert count == 2

    files = sorted(p.name for p in target.glob("*.py"))
    assert files == ["alice_own.py", "bob_shared.py"]


def test_materialize_to_dir_produces_parseable_files(tmp_path):
    _save(
        "alice@example.edu",
        "strip-029",
        description="Drop vendor 029s",
        body=(
            "from marcedit_web.lib.transforms import delete_tags\n"
            "delete_tags(record, '029')\n"
        ),
    )
    target = tmp_path / "mat"
    task_db.materialize_to_dir("alice@example.edu", target)
    parsed = editor.parse_user_task_file(target / "strip_029.py")
    assert parsed["name"] == "strip-029"
    assert parsed["description"] == "Drop vendor 029s"
    assert "delete_tags(record, '029')" in parsed["body"]


def test_materialize_removes_stale_files(tmp_path):
    _save("alice@example.edu", "t1")
    target = tmp_path / "mat"
    task_db.materialize_to_dir("alice@example.edu", target)
    assert (target / "t1.py").exists()

    task_db.delete_task("alice@example.edu", "t1")
    task_db.materialize_to_dir("alice@example.edu", target)
    assert not (target / "t1.py").exists()


def test_materialize_preserves_mtime_when_content_unchanged(tmp_path):
    _save("alice@example.edu", "t1")
    target = tmp_path / "mat"
    task_db.materialize_to_dir("alice@example.edu", target)
    mtime_before = (target / "t1.py").stat().st_mtime

    # Materialize again — file content didn't change → mtime stays put.
    task_db.materialize_to_dir("alice@example.edu", target)
    mtime_after = (target / "t1.py").stat().st_mtime
    assert mtime_before == mtime_after


def test_materialize_rewrites_when_body_changes(tmp_path):
    _save("alice@example.edu", "t1", body="pass\n")
    target = tmp_path / "mat"
    task_db.materialize_to_dir("alice@example.edu", target)
    text_before = (target / "t1.py").read_text()

    _save("alice@example.edu", "t1", body="record.add_field(...)\n")
    task_db.materialize_to_dir("alice@example.edu", target)
    text_after = (target / "t1.py").read_text()
    assert text_before != text_after
