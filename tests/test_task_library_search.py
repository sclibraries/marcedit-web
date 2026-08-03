"""TDD coverage for TASK-193 safe task-library search."""

from marcedit_web.lib import db, task_db, task_library_search


def test_search_indexes_visible_metadata_and_operation_fields_without_private_leaks():
    db.init_schema()
    task_db.save_task(
        owner="alice@example.edu",
        name="add-electronic-genre",
        description="Add electronic genre headings",
        body=(
            '# OP: add-field {"tag":"655","subfields":[["a","Electronic books."]]}'
            "\nrecord.add_field(...)\n"
        ),
    )
    task_db.save_task(
        owner="bob@example.edu",
        name="private-electronic-note",
        description="Electronic private notes",
        body="pass\n",
    )
    task_db.save_task(
        owner="carol@example.edu",
        name="shared-genre",
        description="Shared genre task",
        body="# OP: delete-tag {\"tag\":\"655\"}\nrecord.remove_fields()\n",
        visibility="shared",
    )

    results = task_library_search.search_visible_tasks(
        "alice@example.edu",
        "electronic",
        operation_kind="add-field",
        marc_tag="655",
    )

    assert [row["name"] for row in results] == ["add-electronic-genre"]
    assert "body" not in results[0]
    assert "fingerprint" not in results[0]


def test_malformed_task_remains_searchable_by_safe_name_and_description():
    db.init_schema()
    task_db.save_task(
        owner="alice@example.edu",
        name="legacy-import",
        description="Legacy imported task",
        body="import os\nos.system('nope')\n",
    )

    results = task_library_search.search_visible_tasks(
        "alice@example.edu", "legacy"
    )

    assert [row["name"] for row in results] == ["legacy-import"]
