"""Read-model tests for durable queued operations."""

from __future__ import annotations

import dataclasses
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from marcedit_web.lib import db, operations, sandbox


SAFE_VISIBLE_KEYS = {
    "id", "kind", "submitted_by", "job_id", "job_file_id",
    "source_version_id", "state", "phase", "processed_records",
    "total_records", "output_records", "changed_records", "error_count",
    "terminal_message", "submitted_at", "started_at", "completed_at",
    "artifacts_expire_at", "applied_version_id", "rolled_back_version_id",
    "source_label", "task_names", "summary", "can_cancel",
    "can_access_artifacts", "can_apply_result", "can_rollback_result",
}
ADMIN_DIAGNOSTIC_KEYS = {
    "attempt", "lease_owner", "lease_heartbeat_at", "lease_expires_at",
    "cancel_requested_by", "cancel_requested_at",
}


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


def _completed_job_operation():
    db.init_schema()
    now = "2026-07-16T12:00:00Z"
    with db.connect() as conn:
        job_id = int(conn.execute(
            "INSERT INTO jobs(owner_email,name,created_at,updated_at)"
            " VALUES('owner@smith.edu','Safe view',?,?) RETURNING id",
            (now, now),
        ).fetchone()["id"])
        for email, role in (
            ("owner@smith.edu", "owner"),
            ("editor@smith.edu", "editor"),
            ("viewer@smith.edu", "viewer"),
        ):
            conn.execute(
                "INSERT INTO job_access(job_id,user_email,role,created_at)"
                " VALUES(?,?,?,?)", (job_id, email, role, now),
            )
        file_id = int(conn.execute(
            "INSERT INTO job_files(job_id,display_name,created_by,created_at,"
            "updated_by,updated_at) VALUES(?,'vendor.mrc','owner@smith.edu',?,"
            "'owner@smith.edu',?) RETURNING id", (job_id, now, now),
        ).fetchone()["id"])
        version_id = int(conn.execute(
            "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
            "record_count,file_bytes,source_kind,created_by,created_at)"
            " VALUES(?,1,?,10,100,'upload','owner@smith.edu',?) RETURNING id",
            (file_id, f"/safe-test/{file_id}.mrc", now),
        ).fetchone()["id"])
        conn.execute(
            "UPDATE job_files SET current_version_id=? WHERE id=?",
            (version_id, file_id),
        )
        operation_id = int(conn.execute(
            "INSERT INTO operations(kind,submitted_by,job_id,job_file_id,"
            "source_version_id,state,phase,request_json,total_records,"
            "output_records,changed_records,summary_json,submitted_at,completed_at)"
            " VALUES('saved-task-run','other@smith.edu',?,?,?,'completed',"
            "'completed',?,10,10,2,?, ?, ?) RETURNING id",
            (
                job_id, file_id, version_id,
                json.dumps({"tasks": [{"name": "Safe task", "body": "secret"}]}),
                json.dumps({"changed_records": 2, "internal": "hide"}),
                now, now,
            ),
        ).fetchone()["id"])
    return operation_id


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


def test_visible_read_model_includes_safe_source_and_action_metadata(
    queued_operation, tmp_path,
):
    _attach_input(queued_operation["id"], tmp_path)

    row = operations.list_visible_operations("owner@smith.edu")[0]

    assert row["source_label"] == "input.mrc"
    assert row["can_cancel"] is True
    assert row["can_access_artifacts"] is True
    assert "file_path" not in row


def test_mixed_case_quick_load_submitter_keeps_visibility_and_actions(tmp_path):
    db.init_schema()
    with db.connect() as conn:
        operation_id = int(conn.execute(
            "INSERT INTO operations(kind,submitted_by,state,request_json,"
            "total_records,submitted_at) VALUES"
            "('saved-task-run','Owner@Smith.edu','queued','{}',3,"
            "'2026-07-17T12:00:00Z') RETURNING id"
        ).fetchone()["id"])
    _attach_input(operation_id, tmp_path)

    row = operations.list_visible_operations(" OWNER@SMITH.EDU ")[0]

    assert row["id"] == operation_id
    assert row["can_access_artifacts"] is True
    assert row["can_cancel"] is True
    assert operations.list_artifacts(
        operation_id, "owner@smith.edu"
    )[0]["role"] == "input"
    cancelled = operations.request_cancel(
        operation_id, by="OWNER@smith.edu"
    )
    assert cancelled["state"] == "cancelled"
    assert cancelled["cancel_requested_by"] == "owner@smith.edu"


def test_visible_read_model_is_an_exact_safe_allowlist(queued_operation, tmp_path):
    _attach_input(queued_operation["id"], tmp_path)
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET request_json=?,lease_owner='worker-secret',"
            "lease_token='never-return-this',attempt=3 WHERE id=?",
            (
                json.dumps({"tasks": [{"name": "Visible", "body": "secret body"}]}),
                queued_operation["id"],
            ),
        )

    row = operations.list_visible_operations("owner@smith.edu")[0]

    assert set(row) == SAFE_VISIBLE_KEYS
    assert row["task_names"] == ["Visible"]
    assert row["summary"] == {}
    serialized = json.dumps(row)
    assert "secret body" not in serialized
    assert "never-return-this" not in serialized
    assert "worker-secret" not in serialized


def test_job_action_metadata_matches_current_role_and_state():
    operation_id = _completed_job_operation()

    owner = operations.list_visible_operations("owner@smith.edu")[0]
    editor = operations.list_visible_operations("editor@smith.edu")[0]
    viewer = operations.list_visible_operations("viewer@smith.edu")[0]

    assert owner["id"] == editor["id"] == viewer["id"] == operation_id
    assert owner["can_apply_result"] is True
    assert editor["can_apply_result"] is True
    assert owner["can_cancel"] is False
    assert viewer["can_apply_result"] is False
    assert viewer["can_rollback_result"] is False
    assert viewer["can_access_artifacts"] is True
    assert set(owner) == set(editor) == set(viewer) == SAFE_VISIBLE_KEYS

    with db.connect() as conn:
        operation = conn.execute(
            "SELECT job_file_id,source_version_id FROM operations WHERE id=?",
            (operation_id,),
        ).fetchone()
        applied_version_id = int(conn.execute(
            "INSERT INTO job_file_versions(job_file_id,version_number,"
            "parent_version_id,file_path,record_count,file_bytes,source_kind,"
            "created_by,created_at) VALUES(?,2,?,?,10,100,'queued-task',"
            "'editor@smith.edu','2026-07-16T12:10:00Z') RETURNING id",
            (
                operation["job_file_id"], operation["source_version_id"],
                f"/safe-test/applied-{operation_id}.mrc",
            ),
        ).fetchone()["id"])
        conn.execute(
            "UPDATE job_files SET current_version_id=? WHERE id=?",
            (applied_version_id, operation["job_file_id"]),
        )
        conn.execute(
            "UPDATE operations SET applied_version_id=? WHERE id=?",
            (applied_version_id, operation_id),
        )

    owner = operations.list_visible_operations("owner@smith.edu")[0]
    editor = operations.list_visible_operations("editor@smith.edu")[0]
    viewer = operations.list_visible_operations("viewer@smith.edu")[0]
    assert owner["can_apply_result"] is False
    assert editor["can_apply_result"] is False
    assert owner["can_rollback_result"] is True
    assert editor["can_rollback_result"] is True
    assert viewer["can_rollback_result"] is False


def test_admin_read_model_gets_only_explicit_diagnostics(queued_operation, tmp_path):
    _attach_input(queued_operation["id"], tmp_path)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email,role,status,created_at) VALUES"
            "('admin-view@smith.edu','admin','approved',?)",
            ("2026-07-16T12:00:00Z",),
        )
        conn.execute(
            "UPDATE operations SET request_json=?,lease_owner='worker-a',"
            "lease_token='hidden-token',attempt=2 WHERE id=?",
            (
                json.dumps({"tasks": [{"name": "Visible", "body": "hidden body"}]}),
                queued_operation["id"],
            ),
        )

    row = operations.list_visible_operations("admin-view@smith.edu")[0]

    assert set(row) == SAFE_VISIBLE_KEYS | ADMIN_DIAGNOSTIC_KEYS
    assert row["lease_owner"] == "worker-a"
    assert row["can_cancel"] is True
    assert row["can_access_artifacts"] is False
    assert row["can_apply_result"] is False
    serialized = json.dumps(row)
    assert "hidden-token" not in serialized
    assert "hidden body" not in serialized


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


def test_completion_bounds_each_error_again_at_database_boundary(
    queued_operation, tmp_path
):
    _attach_input(queued_operation["id"], tmp_path)
    candidate = _candidate(tmp_path, queued_operation["id"])
    lease = operations.claim_next("worker-a")
    assert lease is not None
    huge = "x" * (sandbox.MAX_ERROR_MESSAGE_CHARS * 20)

    operations.complete_operation(
        lease,
        result_path=candidate,
        output_records=3,
        changed_records=0,
        error_count=10_000,
        errors=[
            {
                "index": 1,
                "code": huge,
                "task": huge,
                "message": huge,
                "detail": huge,
            }
            for _ in range(sandbox.MAX_RETAINED_ERRORS + 10)
        ],
        summary={},
    )

    retained = operations.list_errors(lease.operation_id, "owner@smith.edu")
    assert len(retained) == sandbox.MAX_RETAINED_ERRORS
    assert len(retained[0]["code"]) <= sandbox.MAX_ERROR_CODE_CHARS
    assert len(retained[0]["task_name"]) <= sandbox.MAX_ERROR_TASK_CHARS
    assert len(retained[0]["message"]) <= sandbox.MAX_ERROR_MESSAGE_CHARS
    assert operations.get_operation(lease.operation_id)["error_count"] == 10_000


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


def test_completion_recognizes_commit_that_persisted_before_acknowledgement_failed(
    queued_operation, tmp_path, monkeypatch
):
    """A lost commit acknowledgement must not roll back published bytes."""
    _attach_input(queued_operation["id"], tmp_path)
    candidate = _candidate(tmp_path, queued_operation["id"])
    lease = operations.claim_next("worker-a")
    assert lease is not None
    real_connect = operations.db.connect
    calls = 0

    @contextmanager
    def commit_then_raise_once():
        nonlocal calls
        calls += 1
        with real_connect() as conn:
            yield conn
            if calls == 1:
                conn.commit()
                raise RuntimeError("commit acknowledgement lost")

    monkeypatch.setattr(operations.db, "connect", commit_then_raise_once)

    completed = operations.complete_operation(
        lease,
        result_path=candidate,
        output_records=3,
        changed_records=2,
        error_count=0,
        errors=[],
        summary={},
    )

    assert completed["state"] == "completed"
    results = [
        row
        for row in operations.list_artifacts(lease.operation_id, "owner@smith.edu")
        if row["role"] == "result"
    ]
    assert len(results) == 1
    assert Path(results[0]["file_path"]).read_bytes() == b"result"
    assert not candidate.exists()


def test_publication_path_is_attempt_specific_after_death_between_rename_and_commit(
    queued_operation, tmp_path, monkeypatch
):
    """A replacement attempt can publish without colliding with orphan bytes."""
    _attach_input(queued_operation["id"], tmp_path)
    first_candidate = _candidate(tmp_path, queued_operation["id"])
    first = operations.claim_next("worker-a")
    assert first is not None
    real_fsync = operations._fsync_file_and_parent

    class SimulatedProcessDeath(BaseException):
        pass

    def die_after_durable_publication(path):
        real_fsync(path)
        raise SimulatedProcessDeath()

    monkeypatch.setattr(
        operations,
        "_fsync_file_and_parent",
        die_after_durable_publication,
    )
    with pytest.raises(SimulatedProcessDeath):
        operations.complete_operation(
            first,
            result_path=first_candidate,
            output_records=3,
            changed_records=2,
            error_count=0,
            errors=[],
            summary={},
        )

    monkeypatch.setattr(operations, "_fsync_file_and_parent", real_fsync)
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET lease_expires_at='2000-01-01T00:00:00Z'"
            " WHERE id=?",
            (first.operation_id,),
        )
    assert operations.recover_expired() == 1
    second = operations.claim_next("worker-b")
    assert second is not None
    second_candidate = (
        operations.operations_root()
        / str(second.operation_id)
        / f"attempt-{second.attempt}"
        / "candidate.mrc"
    )
    second_candidate.parent.mkdir(parents=True)
    second_candidate.write_bytes(b"replacement")

    operations.complete_operation(
        second,
        result_path=second_candidate,
        output_records=3,
        changed_records=2,
        error_count=0,
        errors=[],
        summary={},
    )

    results = [
        row
        for row in operations.list_artifacts(second.operation_id, "owner@smith.edu")
        if row["role"] == "result"
    ]
    assert len(results) == 1
    assert Path(results[0]["file_path"]).read_bytes() == b"replacement"
    assert len(list(Path(results[0]["file_path"]).parent.glob("result-attempt-*"))) == 2
    assert operations.reconcile_operation_storage() == 3
    assert Path(results[0]["file_path"]).read_bytes() == b"replacement"


def test_claim_refuses_second_operation_until_active_lease_is_terminal(tmp_path):
    first_id, _ = _job_operation(submitter="first@smith.edu")
    second_id, _ = _job_operation(submitter="second@smith.edu")
    _attach_input(first_id, tmp_path)
    _attach_input(second_id, tmp_path)

    first = operations.claim_next("worker-a")
    assert first is not None
    assert operations.claim_next("worker-b") is None

    operations.fail_operation(first, code="test", message="finished")
    second = operations.claim_next("worker-b")
    assert second is not None
    assert second.operation_id == second_id


def test_storage_reconciliation_removes_only_unreferenced_queue_workspaces(
    queued_operation, tmp_path
):
    input_path = _attach_input(queued_operation["id"], tmp_path)
    operation_dir = operations.operations_root() / str(queued_operation["id"])
    stale_attempt = operation_dir / "attempt-9"
    stale_attempt.mkdir(parents=True)
    (stale_attempt / "candidate.mrc").write_bytes(b"partial")
    orphan_publication = operation_dir / "result-attempt-8-deadbeef.mrc"
    orphan_publication.write_bytes(b"orphan")
    pending = operations.operations_root() / "pending" / "abandoned.mrc"
    pending.parent.mkdir(parents=True)
    pending.write_bytes(b"pending")

    removed = operations.reconcile_operation_storage()

    assert removed == 3
    assert input_path.exists()
    assert not stale_attempt.exists()
    assert not orphan_publication.exists()
    assert not pending.exists()


def test_storage_reconciliation_unlinks_attempt_symlink_without_following_it(
    queued_operation, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "protected.mrc"
    protected.write_bytes(b"keep")
    operation_dir = operations.operations_root() / str(queued_operation["id"])
    operation_dir.mkdir(parents=True)
    attempt_link = operation_dir / "attempt-7"
    attempt_link.symlink_to(outside, target_is_directory=True)

    assert operations.reconcile_operation_storage() == 1

    assert not attempt_link.exists()
    assert protected.read_bytes() == b"keep"


def test_storage_reconciliation_parent_swap_never_follows_outside_symlink(
    queued_operation, tmp_path, monkeypatch
):
    outside = tmp_path / "outside-race"
    outside.mkdir()
    protected = outside / "protected.mrc"
    protected.write_bytes(b"keep")
    operation_dir = operations.operations_root() / str(queued_operation["id"])
    attempt = operation_dir / "attempt-7"
    attempt.mkdir(parents=True)
    (attempt / "candidate.mrc").write_bytes(b"partial")
    displaced = operation_dir / "displaced"
    real_open = operations.os.open
    swapped = False

    def swap_before_directory_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "attempt-7" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            attempt.rename(displaced)
            attempt.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(operations.os, "open", swap_before_directory_open)

    operations.reconcile_operation_storage()

    assert swapped is True
    assert protected.read_bytes() == b"keep"


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


def test_result_download_limit_is_positive_and_configurable(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_OPERATION_DOWNLOAD_MAX_BYTES", raising=False)
    assert operations.result_download_limit_bytes() == 200 * 1024 * 1024
    monkeypatch.setenv("MARCEDIT_WEB_OPERATION_DOWNLOAD_MAX_BYTES", "1234")
    assert operations.result_download_limit_bytes() == 1234
    monkeypatch.setenv("MARCEDIT_WEB_OPERATION_DOWNLOAD_MAX_BYTES", "0")
    with pytest.raises(operations.OperationError, match="positive integer"):
        operations.result_download_limit_bytes()
