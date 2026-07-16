"""Schema tests for the TASK-156 durable operation queue."""

from __future__ import annotations

import re
import sqlite3

import pytest

from marcedit_web.lib import db


def test_v13_adds_durable_operation_tables():
    db.init_schema()
    with db.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version = conn.execute(
            "SELECT version FROM _schema_version"
        ).fetchone()["version"]
    assert version == 13
    assert {
        "operations",
        "operation_artifacts",
        "operation_events",
        "operation_errors",
        "queue_worker_status",
    }.issubset(tables)


def test_v13_operation_columns_match_the_durable_contract():
    db.init_schema()
    expected = {
        "operations": {
            "id", "kind", "request_version", "submitted_by", "job_id",
            "job_file_id", "source_version_id", "state", "phase",
            "request_json", "processed_records", "total_records",
            "output_records", "changed_records", "error_count", "summary_json",
            "terminal_message", "attempt", "lease_owner", "lease_token",
            "lease_heartbeat_at", "lease_expires_at", "cancel_requested_by",
            "cancel_requested_at", "submitted_at", "started_at", "completed_at",
            "notification_ack_at", "artifacts_expire_at", "applied_version_id",
            "applied_by", "applied_at", "rolled_back_version_id",
            "rolled_back_by", "rolled_back_at",
        },
        "operation_artifacts": {
            "id", "operation_id", "role", "filename", "file_path",
            "record_count", "file_bytes", "queue_owned", "source_version_id",
            "created_at", "expires_at",
        },
        "operation_events": {
            "id", "operation_id", "kind", "message", "actor_email",
            "details_json", "created_at",
        },
        "operation_errors": {
            "id", "operation_id", "ordinal", "record_index", "code",
            "task_name", "message",
        },
        "queue_worker_status": {
            "singleton", "worker_id", "pid", "software_version", "started_at",
            "heartbeat_at", "current_operation_id",
        },
    }
    with db.connect() as conn:
        actual = {
            table: {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table})")
            }
            for table in expected
        }
    assert actual == expected


def test_v13_column_types_nullability_defaults_and_primary_keys_are_exact():
    db.init_schema()
    columns = {
        "operations": (
            {
                "id", "kind", "request_version", "submitted_by", "job_id",
                "job_file_id", "source_version_id", "state", "phase",
                "request_json", "processed_records", "total_records",
                "output_records", "changed_records", "error_count", "summary_json",
                "terminal_message", "attempt", "lease_owner", "lease_token",
                "lease_heartbeat_at", "lease_expires_at", "cancel_requested_by",
                "cancel_requested_at", "submitted_at", "started_at", "completed_at",
                "notification_ack_at", "artifacts_expire_at", "applied_version_id",
                "applied_by", "applied_at", "rolled_back_version_id",
                "rolled_back_by", "rolled_back_at",
            },
            {
                "id", "request_version", "job_id", "job_file_id",
                "source_version_id", "processed_records", "total_records",
                "output_records", "changed_records", "error_count", "attempt",
                "applied_version_id", "rolled_back_version_id",
            },
            {
                "kind", "request_version", "submitted_by", "state", "phase",
                "request_json", "processed_records", "total_records", "error_count",
                "summary_json", "terminal_message", "attempt", "submitted_at",
            },
            {
                "request_version": "1", "phase": "'queued'",
                "processed_records": "0", "error_count": "0",
                "summary_json": "'{}'", "terminal_message": "''", "attempt": "0",
            },
            "id",
        ),
        "operation_artifacts": (
            {
                "id", "operation_id", "role", "filename", "file_path",
                "record_count", "file_bytes", "queue_owned", "source_version_id",
                "created_at", "expires_at",
            },
            {
                "id", "operation_id", "record_count", "file_bytes", "queue_owned",
                "source_version_id",
            },
            {
                "operation_id", "role", "filename", "file_path", "record_count",
                "file_bytes", "queue_owned", "created_at",
            },
            {},
            "id",
        ),
        "operation_events": (
            {
                "id", "operation_id", "kind", "message", "actor_email",
                "details_json", "created_at",
            },
            {"id", "operation_id"},
            {
                "operation_id", "kind", "message", "actor_email", "details_json",
                "created_at",
            },
            {"details_json": "'{}'"},
            "id",
        ),
        "operation_errors": (
            {
                "id", "operation_id", "ordinal", "record_index", "code",
                "task_name", "message",
            },
            {"id", "operation_id", "ordinal", "record_index"},
            {"operation_id", "ordinal", "record_index", "code", "message"},
            {},
            "id",
        ),
        "queue_worker_status": (
            {
                "singleton", "worker_id", "pid", "software_version", "started_at",
                "heartbeat_at", "current_operation_id",
            },
            {"singleton", "pid", "current_operation_id"},
            {"worker_id", "pid", "software_version", "started_at", "heartbeat_at"},
            {},
            "singleton",
        ),
    }
    expected = {}
    for table, (names, integers, required, defaults, primary_key) in columns.items():
        expected[table] = {
            name: (
                "INTEGER" if name in integers else "TEXT",
                int(name in required),
                defaults.get(name),
                int(name == primary_key),
            )
            for name in names
        }
    with db.connect() as conn:
        actual = {
            table: {
                row["name"]: (
                    row["type"], row["notnull"], row["dflt_value"], row["pk"],
                )
                for row in conn.execute(f"PRAGMA table_info({table})")
            }
            for table in columns
        }
    assert actual == expected


def test_v13_uses_autoincrement_for_durable_history_ids():
    db.init_schema()
    with db.connect() as conn:
        definitions = {
            table: conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()["sql"]
            for table in (
                "operations",
                "operation_artifacts",
                "operation_events",
                "operation_errors",
            )
        }
    for definition in definitions.values():
        normalized = re.sub(r"\s+", " ", definition.lower())
        assert "id integer primary key autoincrement" in normalized


def test_v13_adds_operation_lookup_indexes():
    db.init_schema()
    expected = {
        "idx_operations_state_submitted": (
            ("state", 0), ("submitted_at", 0), ("id", 0),
        ),
        "idx_operations_submitter": (("submitted_by", 0), ("submitted_at", 1)),
        "idx_operations_job": (("job_id", 0), ("submitted_at", 1)),
        "idx_operation_events_operation": (("operation_id", 0), ("id", 0)),
        "idx_operation_errors_operation": (("operation_id", 0), ("ordinal", 0)),
        "idx_operation_artifacts_operation": (("operation_id", 0), ("role", 0)),
    }
    with db.connect() as conn:
        actual = {
            name: tuple(
                (row["name"], row["desc"])
                for row in conn.execute(f"PRAGMA index_xinfo({name})")
                if row["key"]
            )
            for name in expected
        }
    assert actual == expected


def test_v13_foreign_keys_preserve_sources_and_cascade_children():
    db.init_schema()
    expected = {
        "operations": {
            ("job_id", "jobs", "id", "NO ACTION"),
            ("job_file_id", "job_files", "id", "NO ACTION"),
            ("source_version_id", "job_file_versions", "id", "NO ACTION"),
            ("applied_version_id", "job_file_versions", "id", "NO ACTION"),
            ("rolled_back_version_id", "job_file_versions", "id", "NO ACTION"),
        },
        "operation_artifacts": {
            ("operation_id", "operations", "id", "CASCADE"),
            ("source_version_id", "job_file_versions", "id", "NO ACTION"),
        },
        "operation_events": {
            ("operation_id", "operations", "id", "CASCADE"),
        },
        "operation_errors": {
            ("operation_id", "operations", "id", "CASCADE"),
        },
        "queue_worker_status": {
            ("current_operation_id", "operations", "id", "NO ACTION"),
        },
    }
    with db.connect() as conn:
        actual = {
            table: {
                (row["from"], row["table"], row["to"], row["on_delete"])
                for row in conn.execute(f"PRAGMA foreign_key_list({table})")
            }
            for table in expected
        }
    assert actual == expected


@pytest.mark.parametrize(
    "column,value",
    [
        ("kind", "unknown"),
        ("request_version", 2),
        ("state", "pending"),
        ("processed_records", -1),
        ("total_records", -1),
        ("output_records", -1),
        ("changed_records", -1),
        ("error_count", -1),
        ("attempt", -1),
    ],
)
def test_v13_rejects_invalid_operation_values(column, value):
    db.init_schema()
    columns = {
        "kind": "saved-task-run",
        "request_version": 1,
        "submitted_by": "owner@smith.edu",
        "state": "queued",
        "request_json": "{}",
        "processed_records": 0,
        "total_records": 1,
        "error_count": 0,
        "attempt": 0,
        "submitted_at": "2026-07-16T12:00:00Z",
    }
    columns[column] = value
    names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute(
                f"INSERT INTO operations ({names}) VALUES ({placeholders})",
                tuple(columns.values()),
            )


@pytest.mark.parametrize(
    "column,value",
    [
        ("role", "preview"),
        ("record_count", -1),
        ("file_bytes", -1),
        ("queue_owned", 2),
    ],
)
def test_v13_rejects_invalid_artifact_values(column, value):
    db.init_schema()
    with db.connect() as conn:
        operation_id = _insert_operation(conn)
        values = {
            "operation_id": operation_id,
            "role": "input",
            "filename": "input.mrc",
            "file_path": "/queue/input.mrc",
            "record_count": 1,
            "file_bytes": 10,
            "queue_owned": 1,
            "created_at": "2026-07-16T12:00:00Z",
        }
        values[column] = value
        names = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"INSERT INTO operation_artifacts ({names})"
                f" VALUES ({placeholders})",
                tuple(values.values()),
            )


def test_v13_rejects_duplicate_artifact_paths():
    db.init_schema()
    with db.connect() as conn:
        first_operation_id = _insert_operation(conn)
        second_operation_id = _insert_operation(conn)
        conn.execute(
            "INSERT INTO operation_artifacts(operation_id, role, filename,"
            " file_path, record_count, file_bytes, queue_owned, created_at)"
            " VALUES (?, 'input', 'first.mrc', '/queue/shared.mrc', 1, 10, 1, ?)",
            (first_operation_id, "2026-07-16T12:00:00Z"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO operation_artifacts(operation_id, role, filename,"
                " file_path, record_count, file_bytes, queue_owned, created_at)"
                " VALUES (?, 'input', 'second.mrc', '/queue/shared.mrc', 1, 10, 1, ?)",
                (second_operation_id, "2026-07-16T12:00:00Z"),
            )


def test_v13_rejects_duplicate_error_ordinals_and_invalid_record_indexes():
    db.init_schema()
    with db.connect() as conn:
        operation_id = _insert_operation(conn)
        conn.execute(
            "INSERT INTO operation_errors(operation_id, ordinal, record_index,"
            " code, message) VALUES (?, 0, 0, 'task-error', 'first')",
            (operation_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO operation_errors(operation_id, ordinal, record_index,"
                " code, message) VALUES (?, 0, 1, 'task-error', 'duplicate')",
                (operation_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO operation_errors(operation_id, ordinal, record_index,"
                " code, message) VALUES (?, 1, -1, 'task-error', 'invalid')",
                (operation_id,),
            )


def test_v13_worker_status_is_a_singleton():
    db.init_schema()
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO queue_worker_status(singleton, worker_id, pid,"
                " software_version, started_at, heartbeat_at)"
                " VALUES (2, 'worker', 1, 'test', ?, ?)",
                ("2026-07-16T12:00:00Z", "2026-07-16T12:00:00Z"),
            )


def test_v13_migrates_an_existing_v12_database():
    db.init_schema()
    with db.connect() as conn:
        for table in (
            "operation_artifacts",
            "operation_events",
            "operation_errors",
            "queue_worker_status",
            "operations",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("UPDATE _schema_version SET version=12")
    db.reset_for_tests()

    db.init_schema()

    with db.connect() as conn:
        version = conn.execute("SELECT version FROM _schema_version").fetchone()
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert version["version"] == 13
    assert {
        "operations",
        "operation_artifacts",
        "operation_events",
        "operation_errors",
        "queue_worker_status",
    }.issubset(tables)
    assert {
        "idx_operations_state_submitted",
        "idx_operations_submitter",
        "idx_operations_job",
        "idx_operation_events_operation",
        "idx_operation_errors_operation",
        "idx_operation_artifacts_operation",
    }.issubset(indexes)


def _insert_operation(conn):
    cursor = conn.execute(
        "INSERT INTO operations(kind, submitted_by, state, request_json,"
        " total_records, submitted_at)"
        " VALUES ('saved-task-run', 'owner@smith.edu', 'queued', '{}', 1, ?)",
        ("2026-07-16T12:00:00Z",),
    )
    return int(cursor.lastrowid)
