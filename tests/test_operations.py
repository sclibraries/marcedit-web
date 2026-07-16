"""Read-model tests for durable queued operations."""

from __future__ import annotations

import dataclasses
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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


def _attach_input(operation_id: int, tmp_path: Path) -> Path:
    path = tmp_path / f"input-{operation_id}.mrc"
    path.write_bytes(b"input")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO operation_artifacts(operation_id, role, filename,"
            " file_path, record_count, file_bytes, queue_owned, created_at)"
            " VALUES (?, 'input', 'input.mrc', ?, 3, 5, 1, ?)",
            (operation_id, str(path), "2026-07-16T12:00:01Z"),
        )
    return path


def _candidate(tmp_path: Path, operation_id: int) -> Path:
    attempt = tmp_path / "operations" / str(operation_id) / "attempt-1"
    attempt.mkdir(parents=True)
    candidate = attempt / "candidate.mrc"
    candidate.write_bytes(b"result")
    return candidate


def test_operations_root_uses_the_isolated_test_directory(tmp_path):
    assert operations.operations_root() == tmp_path / "operations"


def test_retention_days_defaults_to_thirty_and_rejects_invalid_values(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_OPERATION_RETENTION_DAYS", raising=False)
    assert operations.retention_days() == 30
    for value in ("0", "-1", "many"):
        monkeypatch.setenv("MARCEDIT_WEB_OPERATION_RETENTION_DAYS", value)
        with pytest.raises(operations.OperationError, match="positive integer"):
            operations.retention_days()


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


def test_claim_oldest_operation_returns_an_immutable_lease(tmp_path):
    db.init_schema()
    operation_ids = []
    with db.connect() as conn:
        for submitted_at in (
            "2026-07-16T12:00:01Z",
            "2026-07-16T12:00:00Z",
        ):
            cursor = conn.execute(
                "INSERT INTO operations(kind, submitted_by, state, request_json,"
                " total_records, submitted_at)"
                " VALUES ('saved-task-run', 'owner@smith.edu', 'queued', ?, 3, ?)",
                (json.dumps({"tasks": [submitted_at]}), submitted_at),
            )
            operation_ids.append(int(cursor.lastrowid))
    for operation_id in operation_ids:
        _attach_input(operation_id, tmp_path)

    lease = operations.claim_next("worker-a", lease_seconds=30)

    assert lease is not None
    assert lease.operation_id == operation_ids[1]
    assert lease.attempt == 1
    assert lease.request == {"tasks": ["2026-07-16T12:00:00Z"]}
    assert lease.input_artifact["role"] == "input"
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.attempt = 2
    row = operations.get_operation(lease.operation_id)
    assert row["state"] == "running"
    assert row["lease_owner"] == "worker-a"
    assert row["started_at"] is not None
    assert [event["kind"] for event in operations.list_events(
        lease.operation_id, "owner@smith.edu"
    )] == ["claimed"]


def test_claim_rejects_nonpositive_lease_and_returns_none_when_idle():
    with pytest.raises(operations.OperationError, match="lease_seconds must be positive"):
        operations.claim_next("worker-a", lease_seconds=0)
    assert operations.claim_next("worker-a") is None


def test_two_workers_cannot_claim_the_same_operation(queued_operation, tmp_path):
    _attach_input(queued_operation["id"], tmp_path)
    gate = threading.Barrier(2)

    def claim(worker_id):
        gate.wait()
        return operations.claim_next(worker_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(claim, ("worker-a", "worker-b")))

    claimed = [lease for lease in leases if lease is not None]
    assert len(claimed) == 1
    assert claimed[0].operation_id == queued_operation["id"]
    assert operations.get_operation(queued_operation["id"])["attempt"] == 1


def test_lease_renewal_updates_progress_and_rejects_a_stale_token(
    queued_operation, tmp_path,
):
    _attach_input(queued_operation["id"], tmp_path)
    lease = operations.claim_next("worker-a", lease_seconds=1)
    assert lease is not None
    before = operations.get_operation(lease.operation_id)["lease_expires_at"]

    renewed = operations.renew_lease(
        lease, lease_seconds=60, phase="processing", processed_records=2
    )

    assert renewed["phase"] == "processing"
    assert renewed["processed_records"] == 2
    assert renewed["lease_expires_at"] > before
    stale = dataclasses.replace(lease, token="stale")
    with pytest.raises(operations.OperationError, match="operation is no longer running"):
        operations.renew_lease(stale)
    assert operations.is_cancel_requested(stale) is True


def test_submitter_can_cancel_queued_operation_immediately(queued_operation):
    cancelled = operations.request_cancel(
        queued_operation["id"], by="owner@smith.edu"
    )
    assert cancelled["state"] == "cancelled"
    assert cancelled["completed_at"] is not None
    assert [event["kind"] for event in operations.list_events(
        queued_operation["id"], "owner@smith.edu"
    )] == ["cancelled"]


def test_running_cancel_is_observed_and_finished_by_current_lease(
    queued_operation, tmp_path,
):
    _attach_input(queued_operation["id"], tmp_path)
    lease = operations.claim_next("worker-a")
    assert lease is not None
    cancelling = operations.request_cancel(
        queued_operation["id"], by="owner@smith.edu"
    )
    assert cancelling["state"] == "cancelling"
    assert operations.is_cancel_requested(lease) is True

    cancelled = operations.finish_cancelled(lease)

    assert cancelled["state"] == "cancelled"
    assert [event["kind"] for event in operations.list_events(
        queued_operation["id"], "owner@smith.edu"
    )] == ["claimed", "cancel-requested", "cancelled"]


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_editor_and_viewer_cannot_cancel_another_users_job_operation(role):
    operation_id, job_id = _job_operation()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO job_access(job_id, user_email, role, created_at)"
            " VALUES (?, 'collaborator@smith.edu', ?, ?)",
            (job_id, role, "2026-07-16T12:00:00Z"),
        )
    with pytest.raises(operations.OperationError, match="operation not found"):
        operations.request_cancel(operation_id, by="collaborator@smith.edu")


def test_current_job_owner_can_cancel_another_submitters_operation():
    operation_id, job_id = _job_operation(submitter="submitter@smith.edu")
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET owner_email='owner@smith.edu' WHERE id=?", (job_id,)
        )
        conn.execute(
            "UPDATE job_access SET role='editor' WHERE job_id=? AND user_email=?",
            (job_id, "submitter@smith.edu"),
        )
        conn.execute(
            "INSERT INTO job_access(job_id, user_email, role, created_at)"
            " VALUES (?, 'owner@smith.edu', 'owner', ?)",
            (job_id, "2026-07-16T12:00:00Z"),
        )
    assert operations.request_cancel(operation_id, by="owner@smith.edu")[
        "state"
    ] == "cancelled"


def test_approved_admin_can_read_diagnostics_and_cancel_without_source_access(
    queued_operation,
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at)"
            " VALUES ('admin@smith.edu', 'admin', 'approved', ?)",
            ("2026-07-16T12:00:00Z",),
        )
        conn.execute(
            "INSERT INTO operation_errors(operation_id, ordinal, record_index,"
            " code, message) VALUES (?, 0, 1, 'failed', 'safe')",
            (queued_operation["id"],),
        )
    assert queued_operation["id"] in {
        row["id"] for row in operations.list_visible_operations("admin@smith.edu")
    }
    assert operations.list_errors(queued_operation["id"], "admin@smith.edu")
    with pytest.raises(operations.OperationError, match="operation not found"):
        operations.list_artifacts(queued_operation["id"], "admin@smith.edu")
    assert operations.request_cancel(
        queued_operation["id"], by="admin@smith.edu"
    )["state"] == "cancelled"


def test_cancel_rejects_terminal_operation(queued_operation):
    operations.request_cancel(queued_operation["id"], by="owner@smith.edu")
    with pytest.raises(operations.OperationError, match="operation is already finished"):
        operations.request_cancel(queued_operation["id"], by="owner@smith.edu")


def test_cancel_wins_before_completion_transaction(queued_operation, tmp_path):
    _attach_input(queued_operation["id"], tmp_path)
    candidate = _candidate(tmp_path, queued_operation["id"])
    lease = operations.claim_next("worker-a", lease_seconds=30)
    assert lease is not None
    cancelled = operations.request_cancel(
        queued_operation["id"], by="owner@smith.edu"
    )
    assert cancelled["state"] == "cancelling"
    with pytest.raises(
        operations.OperationError,
        match="operation is no longer running",
    ):
        operations.complete_operation(
            lease,
            result_path=candidate,
            output_records=1,
            changed_records=1,
            error_count=0,
            errors=[],
            summary={},
        )
    assert candidate.exists()


def test_completion_wins_before_later_cancel_and_bounds_errors(
    queued_operation, tmp_path,
):
    _attach_input(queued_operation["id"], tmp_path)
    candidate = _candidate(tmp_path, queued_operation["id"])
    lease = operations.claim_next("worker-a")
    assert lease is not None
    errors = [
        {"index": index, "code": "task-error", "task": "Clean", "message": "bad"}
        for index in range(sandbox.MAX_RETAINED_ERRORS + 5)
    ]

    completed = operations.complete_operation(
        lease,
        result_path=candidate,
        output_records=3,
        changed_records=2,
        error_count=999,
        errors=errors,
        summary={"changed": 2},
    )

    assert completed["state"] == "completed"
    assert completed["error_count"] == 999
    assert json.loads(completed["summary_json"]) == {"changed": 2}
    artifacts = operations.list_artifacts(
        queued_operation["id"], "owner@smith.edu"
    )
    result = next(row for row in artifacts if row["role"] == "result")
    assert Path(result["file_path"]).read_bytes() == b"result"
    assert not candidate.exists()
    assert len(operations.list_errors(
        queued_operation["id"], "owner@smith.edu"
    )) == sandbox.MAX_RETAINED_ERRORS
    with pytest.raises(operations.OperationError, match="operation is already finished"):
        operations.request_cancel(queued_operation["id"], by="owner@smith.edu")


def test_completion_restores_candidate_when_database_publication_fails(
    queued_operation, tmp_path,
):
    _attach_input(queued_operation["id"], tmp_path)
    candidate = _candidate(tmp_path, queued_operation["id"])
    lease = operations.claim_next("worker-a")
    assert lease is not None
    with db.connect() as conn:
        conn.execute(
            "CREATE TRIGGER reject_result BEFORE INSERT ON operation_artifacts "
            "WHEN NEW.role='result' BEGIN SELECT RAISE(ABORT, 'reject'); END"
        )

    with pytest.raises(Exception, match="reject"):
        operations.complete_operation(
            lease,
            result_path=candidate,
            output_records=3,
            changed_records=2,
            error_count=0,
            errors=[],
            summary={},
        )

    assert candidate.read_bytes() == b"result"
    assert not (operations.operations_root() / str(lease.operation_id) / "result.mrc").exists()
    assert operations.get_operation(lease.operation_id)["state"] == "running"


def test_fail_operation_requires_current_running_lease(queued_operation, tmp_path):
    _attach_input(queued_operation["id"], tmp_path)
    lease = operations.claim_next("worker-a")
    assert lease is not None
    stale = dataclasses.replace(lease, token="stale")
    with pytest.raises(operations.OperationError, match="operation is no longer running"):
        operations.fail_operation(stale, code="bad-output", message="Failed safely")
    failed = operations.fail_operation(
        lease, code="bad-output", message="Failed safely"
    )
    assert failed["state"] == "failed"
    assert failed["terminal_message"] == "Failed safely"


def test_recover_expired_running_requeues_from_zero_once(
    queued_operation, tmp_path,
):
    _attach_input(queued_operation["id"], tmp_path)
    lease = operations.claim_next("worker-a")
    assert lease is not None
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET processed_records=2, phase='processing',"
            " lease_expires_at='2000-01-01T00:00:00Z' WHERE id=?",
            (lease.operation_id,),
        )
    assert operations.recover_expired() == 1
    assert operations.recover_expired() == 0
    row = operations.get_operation(lease.operation_id)
    assert row["state"] == "queued"
    assert row["processed_records"] == 0
    assert row["phase"] == "queued"
    assert row["lease_token"] is None
    assert [event["kind"] for event in operations.list_events(
        lease.operation_id, "owner@smith.edu"
    )].count("recovered") == 1


def test_recover_expired_cancelling_finishes_cancellation(
    queued_operation, tmp_path,
):
    _attach_input(queued_operation["id"], tmp_path)
    lease = operations.claim_next("worker-a")
    assert lease is not None
    operations.request_cancel(lease.operation_id, by="owner@smith.edu")
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET lease_expires_at='2000-01-01T00:00:00Z'"
            " WHERE id=?", (lease.operation_id,)
        )
    assert operations.recover_expired() == 1
    assert operations.get_operation(lease.operation_id)["state"] == "cancelled"


def test_notification_acknowledgement_is_submitter_owned(queued_operation):
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET state='failed', phase='failed', completed_at=?"
            " WHERE id=?",
            ("2026-07-16T12:05:00Z", queued_operation["id"]),
        )
    with pytest.raises(operations.OperationError, match="operation not found"):
        operations.acknowledge_notification(
            queued_operation["id"], by="other@smith.edu"
        )
    acknowledged = operations.acknowledge_notification(
        queued_operation["id"], by="owner@smith.edu"
    )
    assert acknowledged["notification_ack_at"] is not None


def test_worker_health_uses_persisted_heartbeat_staleness():
    assert operations.worker_health() == {"available": False, "row": None}
    fresh = operations.heartbeat_worker("worker-a", current_operation_id=None)
    assert fresh["worker_id"] == "worker-a"
    assert operations.worker_health(max_age_seconds=15)["available"] is True
    with db.connect() as conn:
        conn.execute(
            "UPDATE queue_worker_status SET heartbeat_at='2000-01-01T00:00:00Z'"
            " WHERE singleton=1"
        )
    health = operations.worker_health(max_age_seconds=15)
    assert health["available"] is False
    assert health["row"]["worker_id"] == "worker-a"
    with pytest.raises(operations.OperationError, match="max_age_seconds must be positive"):
        operations.worker_health(max_age_seconds=0)
