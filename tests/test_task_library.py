"""TDD coverage for TASK-193 task-library persistence."""

from marcedit_web.lib import db


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
