"""TDD coverage for TASK-193 task-library persistence."""

import pytest

from marcedit_web.lib import db, task_db, task_library


def test_folder_schema_is_additive_and_seeds_shared_unfiled_root():
    db.init_schema()

    with db.connect() as conn:
        folder_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(task_folders)")
        }
        task_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tasks)")
        }
        roots = list(
            conn.execute(
                "SELECT scope, owner_email, name FROM task_folders "
                "WHERE parent_id IS NULL ORDER BY scope, owner_email"
            )
        )

    assert {
        "id", "scope", "owner_email", "parent_id", "name", "revision",
        "created_by", "created_at", "updated_at",
    } <= folder_columns
    assert "folder_id" in task_columns
    assert [tuple(row) for row in roots] == [("shared", None, "Unfiled")]


def test_shared_task_name_index_is_partial_and_case_sensitive_to_visibility():
    db.init_schema()

    with db.connect() as conn:
        indexes = list(conn.execute("PRAGMA index_list(tasks)"))
        sql = {
            row["name"]: row["sql"]
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index'"
            )
        }

    names = {row["name"] for row in indexes}
    matching = [name for name in names if "shared" in name and "name" in name]
    assert matching
    assert any(
        sql[name] and "WHERE visibility = 'shared'" in sql[name]
        for name in matching
    )


def test_new_private_task_is_assigned_to_owner_unfiled_folder():
    db.init_schema()
    task_db.save_task(
        owner="alice@example.edu",
        name="strip-029",
        description="Drop 029",
        body="pass\n",
    )

    row = task_db.get_task("alice@example.edu", "strip-029")
    tree = task_library.list_folder_tree("alice@example.edu")

    assert row["folder_id"] is not None
    assert tree[0]["scope"] == "personal"
    assert tree[0]["owner_email"] == "alice@example.edu"
    assert tree[0]["name"] == "Unfiled"
    assert tree[0]["task_ids"] == [row["id"]]


def test_shared_folder_creation_rejects_personal_parent_and_is_audited():
    db.init_schema()
    with pytest.raises(ValueError, match="shared folder"):
        task_library.create_folder(
            "alice@example.edu",
            scope="shared",
            parent_id=99999,
            name="Imports",
        )


def test_task_move_and_rename_preserve_id_folder_and_increment_revision():
    db.init_schema()
    task_db.save_task(
        owner="alice@example.edu",
        name="strip-029",
        description="Drop 029",
        body="pass\n",
    )
    before = task_db.get_task("alice@example.edu", "strip-029")
    personal_root = next(
        folder for folder in task_library.list_folder_tree("alice@example.edu")
        if folder["scope"] == "personal" and folder["parent_id"] is None
    )
    child = task_library.create_folder(
        "alice@example.edu",
        scope="personal",
        parent_id=personal_root["id"],
        name="Imports",
    )

    moved = task_library.move_task(
        "alice@example.edu",
        task_id=before["id"],
        folder_id=child["id"],
        expected_revision=before["revision"],
    )
    renamed = task_library.rename_task(
        "alice@example.edu",
        task_id=before["id"],
        new_name="strip-029-imported",
        expected_revision=moved["revision"],
    )

    assert renamed["id"] == before["id"]
    assert renamed["folder_id"] == child["id"]
    assert renamed["revision"] == before["revision"] + 2
    assert task_db.get_task("alice@example.edu", "strip-029") is None
    assert task_db.get_task("alice@example.edu", "strip-029-imported")["id"] == before["id"]
