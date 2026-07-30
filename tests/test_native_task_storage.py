from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from marcedit_web.lib import db, native_tasks, task_db


FIXTURES = Path(__file__).parent / "fixtures" / "native_tasks"


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def _definition(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_native_save_stores_canonical_definition_and_snapshots_atomically():
    definition = _definition("delete-and-sort.json")
    row = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
        visibility="private",
    )
    compiled = native_tasks.compile_definition(definition)

    assert row["definition_json"] == native_tasks.canonical_definition_json(
        definition
    )
    assert row["body"] == compiled.body
    assert row["extra_imports"] == "\n".join(compiled.imports)
    assert row["compiler_fingerprint"] == (
        native_tasks.current_compiler_fingerprint()
    )
    assert row["revision"] == 1


def test_native_update_requires_expected_revision():
    definition = _definition("delete-and-sort.json")
    created = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    definition["description"] = "Changed"

    with pytest.raises(task_db.NativeTaskConflict, match="expected revision"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition=definition,
        )

    updated = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
        expected_revision=created["revision"],
    )
    assert updated["revision"] == 2
    assert updated["description"] == "Changed"


def test_native_update_rejects_stale_revision_without_mutation():
    definition = _definition("delete-and-sort.json")
    created = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    updated = task_db.save_native_task(
        owner="alice@example.edu",
        definition={**definition, "description": "Revision two"},
        expected_revision=created["revision"],
    )

    with pytest.raises(task_db.NativeTaskConflict, match="expected revision"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition={**definition, "description": "Stale write"},
            expected_revision=created["revision"],
        )

    assert task_db.get_task("alice@example.edu", definition["name"]) == updated


def test_failed_compile_leaves_existing_native_row_byte_identical(monkeypatch):
    definition = _definition("delete-and-sort.json")
    before = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )
    monkeypatch.setattr(
        native_tasks,
        "compile_definition",
        lambda value: (_ for _ in ()).throw(
            native_tasks.NativeDefinitionError("compile failed")
        ),
    )

    with pytest.raises(native_tasks.NativeDefinitionError, match="compile failed"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition={**definition, "description": "not stored"},
            expected_revision=before["revision"],
        )

    assert task_db.get_task("alice@example.edu", definition["name"]) == before


def test_native_artifacts_are_prepared_before_database_connection(monkeypatch):
    definition = _definition("delete-and-sort.json")
    calls = []
    original_validate = native_tasks.validate_definition
    original_canonical = native_tasks.canonical_definition_json
    original_compile = native_tasks.compile_definition
    original_fingerprint = native_tasks.current_compiler_fingerprint

    def record(name, function):
        def wrapper(value=None):
            calls.append(name)
            return function() if value is None else function(value)

        return wrapper

    monkeypatch.setattr(
        native_tasks,
        "validate_definition",
        record("validate", original_validate),
    )
    monkeypatch.setattr(
        native_tasks,
        "canonical_definition_json",
        record("canonical", original_canonical),
    )
    monkeypatch.setattr(
        native_tasks,
        "compile_definition",
        record("compile", original_compile),
    )
    monkeypatch.setattr(
        native_tasks,
        "current_compiler_fingerprint",
        record("fingerprint", original_fingerprint),
    )

    def connect():
        calls.append("connect")
        raise RuntimeError("connection opened")

    monkeypatch.setattr(db, "connect", connect)

    with pytest.raises(RuntimeError, match="connection opened"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition=definition,
        )

    assert max(calls.index(name) for name in {
        "validate", "canonical", "compile", "fingerprint"
    }) < calls.index("connect")


def test_native_save_can_replace_legacy_row_only_with_current_revision():
    definition = _definition("delete-and-sort.json")
    task_db.save_task(
        owner="alice@example.edu",
        name=definition["name"],
        description="Legacy",
        body="pass",
    )
    legacy = task_db.get_task("alice@example.edu", definition["name"])

    with pytest.raises(task_db.NativeTaskConflict, match="expected revision"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition=definition,
        )

    native = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
        expected_revision=legacy["revision"],
    )
    assert native["definition_json"] is not None
    assert native["revision"] == legacy["revision"] + 1


def test_legacy_save_refuses_to_overwrite_native_row():
    definition = _definition("delete-and-sort.json")
    before = task_db.save_native_task(
        owner="alice@example.edu",
        definition=definition,
    )

    with pytest.raises(
        task_db.NativeTaskStorageError,
        match="native tasks must be saved through the native task API",
    ):
        task_db.save_task(
            owner="alice@example.edu",
            name=definition["name"],
            description="Legacy overwrite",
            body="pass",
        )

    assert task_db.get_task("alice@example.edu", definition["name"]) == before


def test_legacy_save_losing_native_conversion_race_preserves_native_row(
    monkeypatch,
):
    definition = _definition("delete-and-sort.json")
    task_db.save_task(
        owner="alice@example.edu",
        name=definition["name"],
        description="Legacy",
        body="pass",
    )
    legacy = task_db.get_task("alice@example.edu", definition["name"])
    original_connect = db.connect
    state = {"connections": 0, "converted": None}

    class InterleavingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, parameters=()):
            if (
                state["converted"] is None
                and statement.startswith("UPDATE tasks SET description")
            ):
                state["converted"] = task_db.save_native_task(
                    owner="alice@example.edu",
                    definition=definition,
                    expected_revision=legacy["revision"],
                )
            return self.connection.execute(statement, parameters)

    @contextmanager
    def interleaving_connect():
        state["connections"] += 1
        with original_connect() as connection:
            if state["connections"] == 1:
                yield InterleavingConnection(connection)
            else:
                yield connection

    monkeypatch.setattr(db, "connect", interleaving_connect)

    with pytest.raises(
        task_db.NativeTaskStorageError,
        match="native tasks must be saved through the native task API",
    ):
        task_db.save_task(
            owner="alice@example.edu",
            name=definition["name"],
            description="Legacy overwrite",
            body="legacy overwrite",
            extra_imports=["from legacy import overwrite"],
        )

    assert state["converted"] is not None
    assert task_db.get_task("alice@example.edu", definition["name"]) == (
        state["converted"]
    )


def test_expected_revision_cannot_create_missing_native_task():
    definition = _definition("delete-and-sort.json")

    with pytest.raises(task_db.NativeTaskConflict, match="expected revision"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition=definition,
            expected_revision=1,
        )

    assert task_db.get_task("alice@example.edu", definition["name"]) is None


def test_native_save_rejects_invalid_visibility_before_connect(monkeypatch):
    monkeypatch.setattr(
        db,
        "connect",
        lambda: (_ for _ in ()).throw(RuntimeError("connection opened")),
    )

    with pytest.raises(ValueError, match="invalid visibility"):
        task_db.save_native_task(
            owner="alice@example.edu",
            definition=_definition("delete-and-sort.json"),
            visibility="public",
        )
