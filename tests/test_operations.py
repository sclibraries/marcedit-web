"""Read-model tests for durable queued operations."""

from __future__ import annotations

import pytest

from marcedit_web.lib import db, operations, sandbox


@pytest.fixture
def queued_operation():
    db.init_schema()
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO operations(kind, submitted_by, state, request_json,"
            " total_records, submitted_at)"
            " VALUES ('saved-task-run', ?, 'queued', '{}', 3, ?)",
            ("owner@smith.edu", "2026-07-16T12:00:00Z"),
        )
        operation_id = int(cursor.lastrowid)
    return operations.get_operation(operation_id)


def _job_operation(*, submitter="owner@smith.edu"):
    db.init_schema()
    with db.connect() as conn:
        job = conn.execute(
            "INSERT INTO jobs(owner_email, name, created_at, updated_at)"
            " VALUES (?, 'Queue test', ?, ?)",
            (submitter, "2026-07-16T11:00:00Z", "2026-07-16T11:00:00Z"),
        )
        job_id = int(job.lastrowid)
        conn.execute(
            "INSERT INTO job_access(job_id, user_email, role, created_at)"
            " VALUES (?, ?, 'owner', ?)",
            (job_id, submitter, "2026-07-16T11:00:00Z"),
        )
        operation = conn.execute(
            "INSERT INTO operations(kind, submitted_by, job_id, state,"
            " request_json, total_records, submitted_at)"
            " VALUES ('saved-task-run', ?, ?, 'queued', '{}', 3, ?)",
            (submitter, job_id, "2026-07-16T12:00:00Z"),
        )
        operation_id = int(operation.lastrowid)
    return operation_id, job_id


def test_operations_root_uses_the_isolated_test_directory(tmp_path):
    assert operations.operations_root() == tmp_path / "operations"


def test_get_operation_returns_a_plain_dict(queued_operation):
    assert type(queued_operation) is dict
    assert queued_operation["submitted_by"] == "owner@smith.edu"


def test_get_operation_rejects_a_missing_id():
    with pytest.raises(operations.OperationError, match="operation not found"):
        operations.get_operation(999)


def test_public_read_model_hides_unrelated_quick_load_operation(
    queued_operation,
):
    visible = operations.list_visible_operations("other@smith.edu")
    assert queued_operation["id"] not in {row["id"] for row in visible}


def test_public_read_model_shows_quick_load_to_its_submitter(queued_operation):
    visible = operations.list_visible_operations("owner@smith.edu")
    assert [row["id"] for row in visible] == [queued_operation["id"]]


def test_job_operation_visibility_follows_current_job_access():
    operation_id, job_id = _job_operation()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO job_access(job_id, user_email, role, created_at)"
            " VALUES (?, 'reviewer@smith.edu', 'viewer', ?)",
            (job_id, "2026-07-16T12:00:00Z"),
        )
    assert operation_id in {
        row["id"]
        for row in operations.list_visible_operations("reviewer@smith.edu")
    }

    with db.connect() as conn:
        conn.execute(
            "DELETE FROM job_access WHERE job_id=? AND user_email=?",
            (job_id, "reviewer@smith.edu"),
        )
    assert operation_id not in {
        row["id"]
        for row in operations.list_visible_operations("reviewer@smith.edu")
    }


def test_job_operation_is_not_visible_to_submitter_after_access_is_removed():
    operation_id, job_id = _job_operation()
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM job_access WHERE job_id=? AND user_email=?",
            (job_id, "owner@smith.edu"),
        )
    assert operation_id not in {
        row["id"]
        for row in operations.list_visible_operations("owner@smith.edu")
    }


def test_artifacts_require_visibility_and_input_artifact_is_internal(
    queued_operation,
    tmp_path,
):
    path = tmp_path / "operations" / "input.mrc"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO operation_artifacts(operation_id, role, filename,"
            " file_path, record_count, file_bytes, queue_owned, created_at)"
            " VALUES (?, 'input', 'input.mrc', ?, 3, 12, 1, ?)",
            (queued_operation["id"], str(path), "2026-07-16T12:00:01Z"),
        )
    assert operations.list_artifacts(
        queued_operation["id"], "owner@smith.edu"
    )[0]["file_path"] == str(path)
    assert operations.input_artifact(queued_operation["id"])["role"] == "input"
    with pytest.raises(operations.OperationError, match="operation not found"):
        operations.list_artifacts(
            queued_operation["id"], "other@smith.edu"
        )


def test_events_are_ordered_and_require_the_same_visibility(queued_operation):
    with db.connect() as conn:
        for kind in ("submitted", "claimed", "completed"):
            conn.execute(
                "INSERT INTO operation_events(operation_id, kind, message,"
                " actor_email, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    queued_operation["id"], kind, kind,
                    "owner@smith.edu", "2026-07-16T12:00:00Z",
                ),
            )
    assert [row["kind"] for row in operations.list_events(
        queued_operation["id"], "owner@smith.edu"
    )] == ["submitted", "claimed", "completed"]
    with pytest.raises(operations.OperationError, match="operation not found"):
        operations.list_events(queued_operation["id"], "other@smith.edu")


def test_error_reads_are_ordered_bounded_and_require_visibility(queued_operation):
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO operation_errors(operation_id, ordinal, record_index,"
            " code, message) VALUES (?, ?, ?, 'task-error', 'failed')",
            [
                (queued_operation["id"], ordinal, ordinal)
                for ordinal in range(sandbox.MAX_RETAINED_ERRORS + 5)
            ],
        )
    errors = operations.list_errors(
        queued_operation["id"], "owner@smith.edu"
    )
    assert len(errors) == sandbox.MAX_RETAINED_ERRORS
    assert [row["ordinal"] for row in errors] == list(
        range(sandbox.MAX_RETAINED_ERRORS)
    )
    with pytest.raises(operations.OperationError, match="operation not found"):
        operations.list_errors(queued_operation["id"], "other@smith.edu")
