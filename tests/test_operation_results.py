"""Review, apply, rollback, and reopen durable queued results (TASK-156)."""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pymarc
import pytest

from marcedit_web.lib import (
    collaboration,
    db,
    job_files,
    jobs,
    operation_results,
    operations,
    session,
)


OWNER = "owner@example.edu"
EDITOR = "editor@example.edu"
VIEWER = "viewer@example.edu"


def _mrc_bytes(record, *, title: str) -> bytes:
    record["245"]["a"] = title
    target = io.BytesIO()
    writer = pymarc.MARCWriter(target)
    writer.write(record)
    return target.getvalue()


def _insert_completed_operation(
    *,
    submitted_by: str,
    input_path: Path,
    result_path: Path,
    job: dict | None = None,
    work_file: dict | None = None,
    expires_at: str = "2099-01-01T00:00:00Z",
) -> int:
    db.init_schema()
    with db.connect() as conn:
        operation_id = int(
            conn.execute(
                "INSERT INTO operations(kind,submitted_by,job_id,job_file_id,"
                "source_version_id,state,phase,request_json,total_records,"
                "output_records,changed_records,summary_json,submitted_at,"
                "completed_at,artifacts_expire_at) VALUES"
                "('saved-task-run',?,?,?,?, 'completed','completed','{}',1,1,1,"
                "'{\"changed_records\": 1}','2026-07-17T12:00:00Z',"
                "'2026-07-17T12:01:00Z',?) RETURNING id",
                (
                    submitted_by,
                    None if job is None else job["id"],
                    None if work_file is None else work_file["id"],
                    None
                    if work_file is None
                    else work_file["current_version_id"],
                    expires_at,
                ),
            ).fetchone()["id"]
        )
        for role, path in (("input", input_path), ("result", result_path)):
            conn.execute(
                "INSERT INTO operation_artifacts(operation_id,role,filename,"
                "file_path,record_count,file_bytes,queue_owned,source_version_id,"
                "created_at,expires_at) VALUES(?,?,?,?,1,?,1,?,"
                "'2026-07-17T12:00:00Z',?)",
                (
                    operation_id,
                    role,
                    path.name,
                    str(path),
                    path.stat().st_size,
                    None
                    if work_file is None
                    else work_file["current_version_id"],
                    expires_at,
                ),
            )
    return operation_id


@pytest.fixture
def completed_job_operation(tmp_path, record, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))
    original_path = tmp_path / "original.mrc"
    original_path.write_bytes(_mrc_bytes(record, title="Original title"))
    result_path = tmp_path / "result.mrc"
    result_path.write_bytes(_mrc_bytes(record, title="Queued result"))
    job = jobs.create_job(OWNER, "Queued review")
    jobs.grant_access(job["id"], EDITOR, "editor", by=OWNER)
    jobs.grant_access(job["id"], VIEWER, "viewer", by=OWNER)
    work_file = job_files.attach_file(
        job_id=job["id"],
        user_email=OWNER,
        source_path=original_path,
        filename="vendor.mrc",
        record_count=1,
        file_bytes=original_path.stat().st_size,
    )
    operation_id = _insert_completed_operation(
        submitted_by=EDITOR,
        input_path=original_path,
        result_path=result_path,
        job=job,
        work_file=work_file,
    )
    return {
        "id": operation_id,
        "job": job,
        "file": work_file,
        "source_bytes": original_path.read_bytes(),
        "result_path": result_path,
    }


def test_apply_creates_version_records_event_and_retains_result(
    completed_job_operation,
):
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    result_before = item["result_path"].read_bytes()

    created = operation_results.apply_job_result(
        item["id"],
        user_email=OWNER,
        opened_version_id=item["file"]["current_version_id"],
    )

    operation = operations.get_operation(item["id"])
    assert created["version_number"] == 2
    assert created["parent_version_id"] == item["file"]["current_version_id"]
    assert created["source_kind"] == "queued-task"
    assert operation["applied_version_id"] == created["id"]
    assert operation["applied_by"] == OWNER
    assert item["result_path"].read_bytes() == result_before
    assert operations.list_events(item["id"], OWNER)[-1]["kind"] == "result-applied"


@pytest.mark.parametrize("user", [VIEWER, "outsider@example.edu"])
def test_apply_requires_current_owner_or_editor_access(
    completed_job_operation,
    user,
):
    item = completed_job_operation
    if user == VIEWER:
        collaboration.acquire_file_checkout(item["file"]["id"], OWNER)

    with pytest.raises(operations.OperationError, match="owner or editor"):
        operation_results.apply_job_result(
            item["id"],
            user_email=user,
            opened_version_id=item["file"]["current_version_id"],
        )


def test_apply_requires_checkout_and_exact_source_version(completed_job_operation):
    item = completed_job_operation
    with pytest.raises(operations.OperationError, match="checkout"):
        operation_results.apply_job_result(
            item["id"],
            user_email=OWNER,
            opened_version_id=item["file"]["current_version_id"],
        )

    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    with pytest.raises(operations.OperationError, match="source version"):
        operation_results.apply_job_result(
            item["id"],
            user_email=OWNER,
            opened_version_id=item["file"]["current_version_id"] + 1,
        )


def test_apply_is_completed_only_and_cannot_be_repeated(completed_job_operation):
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    with db.connect() as conn:
        conn.execute("UPDATE operations SET state='failed' WHERE id=?", (item["id"],))
    with pytest.raises(operations.OperationError, match="completed"):
        operation_results.apply_job_result(
            item["id"],
            user_email=OWNER,
            opened_version_id=item["file"]["current_version_id"],
        )

    with db.connect() as conn:
        conn.execute("UPDATE operations SET state='completed' WHERE id=?", (item["id"],))
    created = operation_results.apply_job_result(
        item["id"],
        user_email=OWNER,
        opened_version_id=item["file"]["current_version_id"],
    )
    with pytest.raises(operations.OperationError, match="already applied"):
        operation_results.apply_job_result(
            item["id"],
            user_email=OWNER,
            opened_version_id=created["id"],
        )


def test_racing_apply_publishes_exactly_one_version(
    completed_job_operation, monkeypatch,
):
    """Two app processes must not publish duplicate queued Job versions."""
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    barrier = threading.Barrier(2)
    original_copy = operation_results._copy_available

    def synchronized_copy(source, target, label):
        original_copy(source, target, label)
        barrier.wait(timeout=2)

    monkeypatch.setattr(operation_results, "_copy_available", synchronized_copy)
    results: list[dict] = []
    errors: list[Exception] = []

    def apply():
        try:
            results.append(
                operation_results.apply_job_result(
                    item["id"],
                    user_email=OWNER,
                    opened_version_id=item["file"]["current_version_id"],
                )
            )
        except Exception as exc:  # captured from the losing contender
            errors.append(exc)

    threads = [threading.Thread(target=apply) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], operations.OperationError)
    assert len(job_files.list_versions(item["file"]["id"], OWNER)) == 2
    operation = operations.get_operation(item["id"])
    assert operation["applied_version_id"] == results[0]["id"]
    action_dir = operations.operations_root() / str(item["id"]) / "actions"
    assert not list(action_dir.glob("*.mrc"))


def test_apply_event_failure_rolls_back_version_and_operation_fields(
    completed_job_operation, monkeypatch,
):
    """Audit metadata failure cannot leave a published, untracked version."""
    item = completed_job_operation
    source_version_id = item["file"]["current_version_id"]
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    original_append = operations._append_event

    def fail_result_event(conn, operation_id, **kwargs):
        if kwargs["kind"] == "result-applied":
            raise RuntimeError("audit storage unavailable")
        return original_append(conn, operation_id, **kwargs)

    monkeypatch.setattr(operations, "_append_event", fail_result_event)

    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        operation_results.apply_job_result(
            item["id"],
            user_email=OWNER,
            opened_version_id=source_version_id,
        )

    operation = operations.get_operation(item["id"])
    assert operation["applied_version_id"] is None
    current = job_files.get_current_version(item["file"]["id"], OWNER)
    assert current["id"] == source_version_id
    assert len(job_files.list_versions(item["file"]["id"], OWNER)) == 1
    assert item["result_path"].exists()
    action_dir = operations.operations_root() / str(item["id"]) / "actions"
    assert not list(action_dir.glob("*.mrc"))


@pytest.mark.parametrize("missing", [False, True])
def test_apply_rejects_expired_or_missing_result(completed_job_operation, missing):
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    if missing:
        item["result_path"].unlink()
        message = "no longer available"
    else:
        with db.connect() as conn:
            conn.execute(
                "UPDATE operation_artifacts SET expires_at='2000-01-01T00:00:00Z'"
                " WHERE operation_id=? AND role='result'",
                (item["id"],),
            )
        message = "expired"

    with pytest.raises(operations.OperationError, match=message):
        operation_results.apply_job_result(
            item["id"],
            user_email=OWNER,
            opened_version_id=item["file"]["current_version_id"],
        )


def test_rollback_creates_child_from_source_without_erasing_applied_version(
    completed_job_operation,
):
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    applied = operation_results.apply_job_result(
        item["id"],
        user_email=OWNER,
        opened_version_id=item["file"]["current_version_id"],
    )

    rolled_back = operation_results.rollback_job_result(
        item["id"], user_email=OWNER, opened_version_id=applied["id"]
    )

    operation = operations.get_operation(item["id"])
    assert rolled_back["version_number"] == 3
    assert rolled_back["parent_version_id"] == applied["id"]
    assert rolled_back["source_kind"] == "queued-task-rollback"
    assert Path(rolled_back["file_path"]).read_bytes() == item["source_bytes"]
    assert job_files.get_version(applied["id"], OWNER) is not None
    assert operation["rolled_back_version_id"] == rolled_back["id"]
    assert operations.list_events(item["id"], OWNER)[-1]["kind"] == "result-rolled-back"

    with pytest.raises(operations.OperationError, match="already rolled back"):
        operation_results.rollback_job_result(
            item["id"], user_email=OWNER, opened_version_id=rolled_back["id"]
        )


def test_racing_rollback_publishes_exactly_one_version(
    completed_job_operation, monkeypatch,
):
    """Concurrent rollback requests cannot publish duplicate restore versions."""
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    applied = operation_results.apply_job_result(
        item["id"],
        user_email=OWNER,
        opened_version_id=item["file"]["current_version_id"],
    )
    barrier = threading.Barrier(2)
    original_copy = operation_results._copy_available

    def synchronized_copy(source, target, label):
        original_copy(source, target, label)
        barrier.wait(timeout=2)

    monkeypatch.setattr(operation_results, "_copy_available", synchronized_copy)
    results: list[dict] = []
    errors: list[Exception] = []

    def rollback():
        try:
            results.append(
                operation_results.rollback_job_result(
                    item["id"],
                    user_email=OWNER,
                    opened_version_id=applied["id"],
                )
            )
        except Exception as exc:  # captured from the losing contender
            errors.append(exc)

    threads = [threading.Thread(target=rollback) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], operations.OperationError)
    assert len(job_files.list_versions(item["file"]["id"], OWNER)) == 3
    operation = operations.get_operation(item["id"])
    assert operation["rolled_back_version_id"] == results[0]["id"]
    events = operations.list_events(item["id"], OWNER)
    assert [event["kind"] for event in events].count("result-rolled-back") == 1
    action_dir = operations.operations_root() / str(item["id"]) / "actions"
    assert not list(action_dir.glob("*.mrc"))


def test_rollback_event_failure_leaves_applied_version_current(
    completed_job_operation, monkeypatch,
):
    """Rollback audit failure rolls back v3, fields, event, and temp bytes."""
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    applied = operation_results.apply_job_result(
        item["id"],
        user_email=OWNER,
        opened_version_id=item["file"]["current_version_id"],
    )
    original_append = operations._append_event

    def fail_rollback_event(conn, operation_id, **kwargs):
        if kwargs["kind"] == "result-rolled-back":
            raise RuntimeError("rollback audit unavailable")
        return original_append(conn, operation_id, **kwargs)

    monkeypatch.setattr(operations, "_append_event", fail_rollback_event)

    with pytest.raises(RuntimeError, match="rollback audit unavailable"):
        operation_results.rollback_job_result(
            item["id"], user_email=OWNER, opened_version_id=applied["id"]
        )

    operation = operations.get_operation(item["id"])
    assert operation["rolled_back_version_id"] is None
    assert operation["rolled_back_by"] is None
    assert operation["rolled_back_at"] is None
    current = job_files.get_current_version(item["file"]["id"], OWNER)
    assert current["id"] == applied["id"]
    assert len(job_files.list_versions(item["file"]["id"], OWNER)) == 2
    events = operations.list_events(item["id"], OWNER)
    assert "result-rolled-back" not in [event["kind"] for event in events]
    action_dir = operations.operations_root() / str(item["id"]) / "actions"
    assert not list(action_dir.glob("*.mrc"))


def test_editor_can_roll_back_applied_result(completed_job_operation):
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    applied = operation_results.apply_job_result(
        item["id"],
        user_email=OWNER,
        opened_version_id=item["file"]["current_version_id"],
    )
    collaboration.release_file_checkout(item["file"]["id"], OWNER)
    collaboration.acquire_file_checkout(item["file"]["id"], EDITOR)

    rolled_back = operation_results.rollback_job_result(
        item["id"], user_email=EDITOR, opened_version_id=applied["id"]
    )

    assert rolled_back["created_by"] == EDITOR
    assert operations.get_operation(item["id"])["rolled_back_by"] == EDITOR


@pytest.mark.parametrize("user", [VIEWER, "outsider@example.edu"])
def test_rollback_denies_viewer_and_outsider(completed_job_operation, user):
    item = completed_job_operation
    collaboration.acquire_file_checkout(item["file"]["id"], OWNER)
    applied = operation_results.apply_job_result(
        item["id"],
        user_email=OWNER,
        opened_version_id=item["file"]["current_version_id"],
    )

    with pytest.raises(operations.OperationError, match="owner or editor"):
        operation_results.rollback_job_result(
            item["id"], user_email=user, opened_version_id=applied["id"]
        )


@pytest.fixture
def completed_quick_operation(tmp_path, record):
    original = tmp_path / "vendor-original.mrc"
    original.write_bytes(_mrc_bytes(record, title="Original quick load"))
    result = tmp_path / "result.mrc"
    result.write_bytes(_mrc_bytes(record, title="Queued quick result"))
    return {
        "id": _insert_completed_operation(
            submitted_by=OWNER,
            input_path=original,
            result_path=result,
        ),
        "original": original,
        "result": result,
    }


@pytest.mark.parametrize(
    ("use_result", "expected_filename"),
    [
        (False, "vendor-original-original.mrc"),
        (True, "vendor-original-queued-result.mrc"),
    ],
)
def test_reopen_quick_load_replaces_store_and_retains_artifacts(
    completed_quick_operation,
    use_result,
    expected_filename,
    monkeypatch,
):
    item = completed_quick_operation
    state = {
        "user": OWNER,
        "store": None,
        "job_file_id": 99,
        "job_file_version_id": 100,
        "quick_load_mode": False,
    }
    fake_st = SimpleNamespace(session_state=state, query_params={"job_file": "99"})
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    store = operation_results.reopen_quick_load(
        item["id"], user_email=OWNER, use_result=use_result
    )

    assert store.filename == expected_filename
    assert state["store"] is store
    assert state["job_file_id"] is None
    assert state["job_file_version_id"] is None
    assert state["quick_load_mode"] is True
    assert "job_file" not in fake_st.query_params
    assert item["original"].exists()
    assert item["result"].exists()


def test_reopen_quick_load_rejects_cross_user_and_expired_artifact(
    completed_quick_operation,
    monkeypatch,
):
    item = completed_quick_operation
    state = {"user": OWNER, "store": None}
    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(session_state=state))
    with pytest.raises(operations.OperationError, match="not found"):
        operation_results.reopen_quick_load(
            item["id"], user_email=EDITOR, use_result=True
        )

    with db.connect() as conn:
        conn.execute(
            "UPDATE operation_artifacts SET expires_at='2000-01-01T00:00:00Z'"
            " WHERE operation_id=? AND role='input'",
            (item["id"],),
        )
    with pytest.raises(operations.OperationError, match="expired"):
        operation_results.reopen_quick_load(
            item["id"], user_email=OWNER, use_result=False
        )
