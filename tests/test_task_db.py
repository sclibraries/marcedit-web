"""Tests for marcedit_web.lib.task_db (TASK-050)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marcedit_web.lib import db, editor, native_tasks, task_db


FIXTURES = Path(__file__).parent / "fixtures" / "native_tasks"


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
    assert after["revision"] == before["revision"] + 1


def test_save_task_renames_in_place_when_given_task_identity():
    _save("cataloger@example.edu", "old-name", description="before")
    original = task_db.get_task("cataloger@example.edu", "old-name")

    task_db.save_task(
        owner="cataloger@example.edu",
        name="new-name",
        description="after",
        body="pass\n# changed\n",
        task_id=original["id"],
        expected_revision=original["revision"],
    )

    assert task_db.get_task("cataloger@example.edu", "old-name") is None
    renamed = task_db.get_task("cataloger@example.edu", "new-name")
    assert renamed["id"] == original["id"]
    assert renamed["folder_id"] == original["folder_id"]
    assert renamed["revision"] == original["revision"] + 1
    assert renamed["description"] == "after"
    assert renamed["body"] == "pass\n# changed\n"


def test_shared_task_edit_preserves_owner_and_visibility_for_other_actor():
    _save("owner@example.edu", "shared-task", visibility="shared")
    original = task_db.get_task("owner@example.edu", "shared-task")

    task_db.save_task(
        owner="owner@example.edu",
        actor="editor@example.edu",
        name="shared-task",
        description="edited by collaborator",
        body="pass\n# collaborator\n",
        visibility="shared",
        task_id=original["id"],
        expected_revision=original["revision"],
    )

    updated = task_db.get_task("owner@example.edu", "shared-task")
    assert updated["owner_email"] == "owner@example.edu"
    assert updated["visibility"] == "shared"
    assert updated["folder_id"] == original["folder_id"]
    assert updated["revision"] == original["revision"] + 1
    assert updated["description"] == "edited by collaborator"


def test_shared_task_rename_is_owner_only():
    _save("owner@example.edu", "shared-task", visibility="shared")
    original = task_db.get_task("owner@example.edu", "shared-task")

    with pytest.raises(ValueError, match="rename"):
        task_db.save_task(
            owner="owner@example.edu",
            actor="editor@example.edu",
            name="renamed-by-collaborator",
            description="edited by collaborator",
            body="pass\n",
            visibility="shared",
            task_id=original["id"],
            expected_revision=original["revision"],
        )

    unchanged = task_db.get_task("owner@example.edu", "shared-task")
    assert unchanged["id"] == original["id"]
    assert unchanged["revision"] == original["revision"]
    assert task_db.get_task("owner@example.edu", "renamed-by-collaborator") is None


def test_shared_task_collaborator_cannot_make_task_private():
    _save("owner@example.edu", "shared-task", visibility="shared")
    original = task_db.get_task("owner@example.edu", "shared-task")

    with pytest.raises(ValueError, match="not authorized"):
        task_db.save_task(
            owner="owner@example.edu",
            actor="editor@example.edu",
            name="shared-task",
            description="must remain shared",
            body="pass\n",
            visibility="private",
            task_id=original["id"],
            expected_revision=original["revision"],
        )

    unchanged = task_db.get_task("owner@example.edu", "shared-task")
    assert unchanged["visibility"] == "shared"
    assert unchanged["revision"] == original["revision"]


def test_private_task_edit_rejects_non_owner_actor():
    _save("owner@example.edu", "private-task")
    original = task_db.get_task("owner@example.edu", "private-task")

    with pytest.raises(ValueError, match="not authorized"):
        task_db.save_task(
            owner="owner@example.edu",
            actor="editor@example.edu",
            name="private-task",
            description="must not change",
            body="pass\n# denied\n",
            task_id=original["id"],
            expected_revision=original["revision"],
        )


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


def test_duplicate_shared_task_creation_is_cataloger_facing():
    _save("alice@example.edu", "shared-name", visibility="shared")

    with pytest.raises(ValueError, match="already exists"):
        _save("bob@example.edu", "shared-name", visibility="shared")


def test_set_visibility_conflict_is_cataloger_facing_and_atomic():
    _save("alice@example.edu", "already-shared", visibility="shared")
    _save("bob@example.edu", "already-shared", visibility="private")
    before = task_db.get_task("bob@example.edu", "already-shared")

    with pytest.raises(ValueError, match="already exists"):
        task_db.set_visibility("bob@example.edu", "already-shared", "shared")

    after = task_db.get_task("bob@example.edu", "already-shared")
    assert after["visibility"] == "private"
    assert after["revision"] == before["revision"]


def test_set_visibility_toggle():
    _save("alice@example.edu", "t1", visibility="private")
    created = task_db.get_task("alice@example.edu", "t1")
    task_db.set_visibility("alice@example.edu", "t1", "shared")
    shared = task_db.get_task("alice@example.edu", "t1")
    assert shared["visibility"] == "shared"
    assert shared["revision"] == created["revision"] + 1
    task_db.set_visibility("alice@example.edu", "t1", "private")
    private = task_db.get_task("alice@example.edu", "t1")
    assert private["visibility"] == "private"
    assert private["revision"] == shared["revision"] + 1


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


def test_materialize_valid_native_task_to_parseable_python(tmp_path):
    definition = json.loads(
        (FIXTURES / "delete-and-sort.json").read_text(encoding="utf-8")
    )
    task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )

    target = tmp_path / "mat"
    task_db.materialize_to_dir("alice@example.edu", target)

    parsed = editor.parse_user_task_file(target / "delete_vendor_field.py")
    assert parsed["body"] == native_tasks.compile_definition(definition).body


def test_materialize_migrates_stale_native_task_before_writing(tmp_path):
    definition = json.loads(
        (FIXTURES / "delete-and-sort.json").read_text(encoding="utf-8")
    )
    created = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
        visibility="shared",
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET compiler_fingerprint = ?, body = ? WHERE id = ?",
            ("0" * 64, "old body", created["id"]),
        )

    target = tmp_path / "mat"
    task_db.materialize_to_dir("viewer@example.edu", target)

    prepared = task_db.get_task("alice@example.edu", definition["name"])
    parsed = editor.parse_user_task_file(target / "delete_vendor_field.py")
    assert prepared["compiler_fingerprint"] == (
        native_tasks.current_compiler_fingerprint()
    )
    assert parsed["body"] == prepared["body"]


def test_materialize_integrity_failure_writes_no_native_task_file(tmp_path):
    definition = json.loads(
        (FIXTURES / "delete-and-sort.json").read_text(encoding="utf-8")
    )
    created = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET body = ? WHERE id = ?",
            ("tampered", created["id"]),
        )

    target = tmp_path / "mat"
    with pytest.raises(task_db.NativeTaskIntegrityError, match="body"):
        task_db.materialize_to_dir("alice@example.edu", target)

    assert not (target / "delete_vendor_field.py").exists()


def test_materialize_integrity_failure_removes_previous_native_task_file(tmp_path):
    definition = json.loads(
        (FIXTURES / "delete-and-sort.json").read_text(encoding="utf-8")
    )
    created = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    target = tmp_path / "mat"
    path = target / "delete_vendor_field.py"
    task_db.materialize_to_dir("alice@example.edu", target)
    assert path.exists()

    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET body = ? WHERE id = ?",
            ("tampered", created["id"]),
        )

    with pytest.raises(task_db.NativeTaskIntegrityError, match="body"):
        task_db.materialize_to_dir("alice@example.edu", target)

    assert not path.exists()
