"""TDD coverage for TASK-193 safe task-library search."""

import json
from datetime import datetime, timedelta, timezone

from marcedit_web.lib import db, task_db, task_library, task_library_search


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


def test_native_definition_steps_are_searchable_by_action_and_tag():
    from pathlib import Path

    definition = json.loads(
        Path("tests/fixtures/native_tasks/build-field.json").read_text()
    )
    metadata = task_library_search._operation_metadata({
        "definition_json": json.dumps(definition),
        "body": "",
    })

    assert metadata["operation_kinds"] == ["build_field"]
    assert metadata["marc_tags"] == ["001", "003", "876"]


def test_search_does_not_index_instruction_fingerprints():
    db.init_schema()
    fingerprint = "a" * 64
    task_db.save_task(
        owner="carol@example.edu",
        name="shared-migration",
        description="Shared migration task",
        body=(
            '# OP: migration-blocker '
            + json.dumps({"instruction_sha256": fingerprint})
            + "\npass\n"
        ),
        visibility="shared",
    )

    results = task_library_search.search_visible_tasks(
        "alice@example.edu", fingerprint
    )

    assert results == []


def test_search_indexes_folder_path_subfields_literals_and_import_source():
    db.init_schema()
    task_db.save_task(
        owner="alice@example.edu",
        name="imported-856-links",
        description="Imported from vendor-links.tasksfile.txt",
        body=(
            '# OP: guided-find-replace '
            + json.dumps({
                "tag": "856",
                "subfield": "u",
                "find": "old.example",
                "replacement": "new.example",
            })
            + "\npass\n"
        ),
    )
    root = next(
        folder for folder in task_library.list_folder_tree("alice@example.edu")
        if folder["scope"] == "personal"
    )
    folder = task_library.create_folder(
        "alice@example.edu",
        scope="personal",
        parent_id=root["id"],
        name="Vendor Imports",
    )
    task = task_db.get_task("alice@example.edu", "imported-856-links")
    task_library.move_task(
        "alice@example.edu",
        task_id=task["id"],
        folder_id=folder["id"],
        expected_revision=task["revision"],
    )

    results = task_library_search.search_visible_tasks(
        "alice@example.edu",
        "vendor-links",
        subfield_code="u",
        imported_source="vendor-links.tasksfile.txt",
        folder_id=folder["id"],
    )

    assert len(results) == 1
    assert results[0]["folder_path"] == "My Tasks / Unfiled / Vendor Imports"
    assert results[0]["subfield_codes"] == ["u"]
    assert results[0]["literal_values"] == ["new.example", "old.example"]
    assert results[0]["imported_sources"] == ["vendor-links.tasksfile.txt"]


def test_search_filters_owner_visibility_validation_and_recent_updates():
    db.init_schema()
    task_db.save_task(
        owner="alice@example.edu",
        name="recent-shared",
        description="recent",
        body="# OP: delete-tag {\"tag\": \"655\"}\npass\n",
        visibility="shared",
    )
    task_db.save_task(
        owner="bob@example.edu",
        name="old-shared",
        description="old",
        body="pass\n",
        visibility="shared",
    )
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET updated_at=? WHERE owner_email=? AND name=?",
            (old, "bob@example.edu", "old-shared"),
        )

    results = task_library_search.search_visible_tasks(
        "carol@example.edu",
        visibility="shared",
        owner="alice@example.edu",
        validation_state="legacy",
        recent_days=1,
    )

    assert [row["name"] for row in results] == ["recent-shared"]


def test_search_operation_aliases_and_folder_selection_include_descendants():
    db.init_schema()
    task_db.save_task(
        owner="alice@example.edu",
        name="nested-build",
        description="",
        body="# OP: build-field {\"tag\": \"876\"}\npass\n",
    )
    root = next(
        folder for folder in task_library.list_folder_tree("alice@example.edu")
        if folder["scope"] == "personal"
    )
    child = task_library.create_folder(
        "alice@example.edu",
        scope="personal",
        parent_id=root["id"],
        name="Nested",
    )
    task = task_db.get_task("alice@example.edu", "nested-build")
    task_library.move_task(
        "alice@example.edu",
        task_id=task["id"],
        folder_id=child["id"],
        expected_revision=task["revision"],
    )

    results = task_library_search.search_visible_tasks(
        "alice@example.edu",
        operation_kind="build-field",
        folder_id=root["id"],
    )

    assert [row["name"] for row in results] == ["nested-build"]
