from __future__ import annotations

import sqlite3

from marcedit_web.lib import db


def test_v13_to_v14_preserves_legacy_tasks_and_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE tasks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_email   TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            description   TEXT    NOT NULL DEFAULT '',
            body          TEXT    NOT NULL,
            extra_imports TEXT    NOT NULL DEFAULT '',
            visibility    TEXT    NOT NULL DEFAULT 'private'
                          CHECK(visibility IN ('private','shared')),
            created_at    TEXT    NOT NULL,
            updated_at    TEXT    NOT NULL,
            UNIQUE(owner_email, name)
        );
        CREATE TABLE _schema_version (
            version INTEGER NOT NULL
        );
        INSERT INTO _schema_version(version) VALUES (13);
        INSERT INTO tasks(
            owner_email, name, description, body, extra_imports,
            visibility, created_at, updated_at
        ) VALUES (
            'alice@example.edu', 'legacy-task', 'Legacy', 'pass', '',
            'private', '2026-07-30T00:00:00Z', '2026-07-30T00:00:00Z'
        );
    """)

    db._migrate_to_v14(conn)
    db._migrate_to_v14(conn)

    task_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(tasks)")
    }
    row = conn.execute(
        "SELECT * FROM tasks WHERE owner_email = ? AND name = ?",
        ("alice@example.edu", "legacy-task"),
    ).fetchone()

    assert db.SCHEMA_VERSION == 14
    assert {
        "definition_json",
        "compiler_fingerprint",
        "revision",
    }.issubset(task_columns)
    assert row["body"] == "pass"
    assert row["extra_imports"] == ""
    assert row["definition_json"] is None
    assert row["compiler_fingerprint"] is None
    assert row["revision"] == 1
