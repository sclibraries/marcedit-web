"""Immutable queued task-submission tests for TASK-156."""

from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import (
    db,
    job_files,
    jobs,
    operation_submission,
    operations,
    sandbox,
)


@pytest.fixture(autouse=True)
def _isolated_job_files_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))


def sample_mrc_bytes() -> bytes:
    output = io.BytesIO()
    writer = pymarc.MARCWriter(output)
    for control_number in ("1", "2"):
        record = pymarc.Record()
        record.add_field(pymarc.Field(tag="001", data=control_number))
        writer.write(record)
    writer.close(close_fh=False)
    return output.getvalue()


def _task(name: str = "first") -> sandbox.TaskSpec:
    return sandbox.TaskSpec(
        name=name,
        body="record['001'].data += 'x'",
        imports=["re"],
    )


def _attached_file(tmp_path: Path, *, owner: str = "owner@smith.edu"):
    source = tmp_path / "job-source.mrc"
    source.write_bytes(sample_mrc_bytes())
    job = jobs.create_job(owner, "Queued task test")
    attached = job_files.attach_file(
        job_id=job["id"],
        user_email=owner,
        source_path=source,
        filename="job-source.mrc",
        record_count=2,
        file_bytes=source.stat().st_size,
    )
    version = job_files.get_current_version(attached["id"], owner)
    return job, attached, version


def test_quick_load_submission_snapshots_order_and_copies_input(tmp_path):
    source = tmp_path / "vendor.mrc"
    source.write_bytes(sample_mrc_bytes())
    created = operation_submission.submit_quick_load_task_run(
        user_email="owner@smith.edu",
        source_path=source,
        filename="vendor.mrc",
        record_count=2,
        task_specs=[
            sandbox.TaskSpec(name="first", body="record['001'].data = '1'"),
            sandbox.TaskSpec(name="second", body="record['001'].data += '2'"),
        ],
    )
    source.write_bytes(b"changed after submission")
    request = json.loads(created["request_json"])
    artifact = operations.input_artifact(created["id"])
    assert [task["name"] for task in request["tasks"]] == ["first", "second"]
    assert Path(artifact["file_path"]).read_bytes() == sample_mrc_bytes()
    assert artifact["queue_owned"] == 1


def test_submission_snapshot_does_not_follow_later_task_mutation(tmp_path):
    source = tmp_path / "vendor.mrc"
    source.write_bytes(sample_mrc_bytes())
    task = _task()
    created = operation_submission.submit_quick_load_task_run(
        user_email="owner@smith.edu",
        source_path=source,
        filename="vendor.mrc",
        record_count=2,
        task_specs=[task],
    )

    task.name = "changed"
    task.body = "raise RuntimeError('changed')"
    task.imports.append("os")

    assert json.loads(created["request_json"])["tasks"] == [
        {
            "name": "first",
            "body": "record['001'].data += 'x'",
            "imports": ["re"],
        }
    ]


def test_job_submission_allows_editor_without_checkout_and_uses_exact_version(
    tmp_path,
):
    job, attached, version = _attached_file(tmp_path)
    jobs.grant_access(job["id"], "editor@smith.edu", "editor", by="owner@smith.edu")

    created = operation_submission.submit_job_task_run(
        user_email="editor@smith.edu",
        file_id=attached["id"],
        source_version_id=version["id"],
        task_specs=[_task()],
    )

    artifact = operations.input_artifact(created["id"])
    assert created["job_id"] == job["id"]
    assert created["job_file_id"] == attached["id"]
    assert created["source_version_id"] == version["id"]
    assert artifact["source_version_id"] == version["id"]
    assert artifact["file_path"] == version["file_path"]
    assert artifact["queue_owned"] == 0


def test_job_submission_rejects_viewer_access(tmp_path):
    job, attached, version = _attached_file(tmp_path)
    jobs.grant_access(job["id"], "viewer@smith.edu", "viewer", by="owner@smith.edu")

    with pytest.raises(jobs.JobError, match="access denied"):
        operation_submission.submit_job_task_run(
            user_email="viewer@smith.edu",
            file_id=attached["id"],
            source_version_id=version["id"],
            task_specs=[_task()],
        )


def test_job_submission_rejects_version_from_another_file(tmp_path):
    job, attached, _ = _attached_file(tmp_path)
    other_source = tmp_path / "other.mrc"
    other_source.write_bytes(sample_mrc_bytes())
    other = job_files.attach_file(
        job_id=job["id"],
        user_email="owner@smith.edu",
        source_path=other_source,
        filename="other.mrc",
        record_count=2,
        file_bytes=other_source.stat().st_size,
    )
    other_version = job_files.get_current_version(other["id"], "owner@smith.edu")

    with pytest.raises(operations.OperationError, match="version does not belong"):
        operation_submission.submit_job_task_run(
            user_email="owner@smith.edu",
            file_id=attached["id"],
            source_version_id=other_version["id"],
            task_specs=[_task()],
        )


def test_job_submission_rechecks_editor_access_inside_insert_transaction(
    tmp_path,
    monkeypatch,
):
    job, attached, version = _attached_file(tmp_path)
    editor = "editor@smith.edu"
    owner = "owner@smith.edu"
    jobs.grant_access(job["id"], editor, "editor", by=owner)
    original_get_version = operation_submission.job_files.get_version

    def get_version_then_revoke(version_id, user_email):
        row = original_get_version(version_id, user_email)
        assert jobs.revoke_access(job["id"], editor, by=owner)
        return row

    monkeypatch.setattr(
        operation_submission.job_files,
        "get_version",
        get_version_then_revoke,
    )

    with pytest.raises(jobs.JobError, match="access denied"):
        operation_submission.submit_job_task_run(
            user_email=editor,
            file_id=attached["id"],
            source_version_id=version["id"],
            task_specs=[_task()],
        )

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


@pytest.mark.parametrize("source_kind", ["quick-load", "job"])
def test_submission_returns_captured_row_without_a_public_post_commit_read(
    tmp_path,
    monkeypatch,
    source_kind,
):
    if source_kind == "quick-load":
        source = tmp_path / "vendor.mrc"
        source.write_bytes(sample_mrc_bytes())

        def submit():
            return operation_submission.submit_quick_load_task_run(
                user_email="owner@smith.edu",
                source_path=source,
                filename="vendor.mrc",
                record_count=2,
                task_specs=[_task()],
            )

    else:
        _, attached, version = _attached_file(tmp_path)

        def submit():
            return operation_submission.submit_job_task_run(
                user_email="owner@smith.edu",
                file_id=attached["id"],
                source_version_id=version["id"],
                task_specs=[_task()],
            )

    def reject_post_read(operation_id):
        raise AssertionError(f"unexpected public post-read for {operation_id}")

    monkeypatch.setattr(operations, "get_operation", reject_post_read)

    created = submit()

    assert created["state"] == "queued"
    assert operations.input_artifact(created["id"])["role"] == "input"


@pytest.mark.parametrize("submit_kind", ["quick-load", "job"])
def test_submission_rejects_an_empty_task_selection(tmp_path, submit_kind):
    if submit_kind == "quick-load":
        source = tmp_path / "vendor.mrc"
        source.write_bytes(sample_mrc_bytes())
        submit = lambda: operation_submission.submit_quick_load_task_run(
            user_email="owner@smith.edu",
            source_path=source,
            filename="vendor.mrc",
            record_count=2,
            task_specs=[],
        )
    else:
        _, attached, version = _attached_file(tmp_path)
        submit = lambda: operation_submission.submit_job_task_run(
            user_email="owner@smith.edu",
            file_id=attached["id"],
            source_version_id=version["id"],
            task_specs=[],
        )

    with pytest.raises(operations.OperationError, match="select at least one task"):
        submit()


def test_quick_load_submission_rejects_an_unreadable_source(tmp_path):
    with pytest.raises(operations.OperationError, match="readable MARC file"):
        operation_submission.submit_quick_load_task_run(
            user_email="owner@smith.edu",
            source_path=tmp_path / "missing.mrc",
            filename="missing.mrc",
            record_count=0,
            task_specs=[_task()],
        )


def test_quick_load_submission_validates_record_count(tmp_path):
    source = tmp_path / "vendor.mrc"
    source.write_bytes(sample_mrc_bytes())
    with pytest.raises(operations.OperationError, match="record count does not match"):
        operation_submission.submit_quick_load_task_run(
            user_email="owner@smith.edu",
            source_path=source,
            filename="vendor.mrc",
            record_count=1,
            task_specs=[_task()],
        )


def test_quick_load_submission_preserves_seeded_target_collision(tmp_path):
    db.init_schema()
    collision = operations.operations_root() / "1" / "input.mrc"
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"unrelated existing bytes")
    source = tmp_path / "vendor.mrc"
    source.write_bytes(sample_mrc_bytes())

    with pytest.raises(
        operations.OperationError,
        match="artifact directory already exists",
    ):
        operation_submission.submit_quick_load_task_run(
            user_email="owner@smith.edu",
            source_path=source,
            filename="vendor.mrc",
            record_count=2,
            task_specs=[_task()],
        )

    assert collision.read_bytes() == b"unrelated existing bytes"
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


def test_quick_load_expiry_uses_configured_retention_interval(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_OPERATION_RETENTION_DAYS", "7")
    source = tmp_path / "vendor.mrc"
    source.write_bytes(sample_mrc_bytes())

    created = operation_submission.submit_quick_load_task_run(
        user_email="owner@smith.edu",
        source_path=source,
        filename="vendor.mrc",
        record_count=2,
        task_specs=[_task()],
    )

    artifact = operations.input_artifact(created["id"])
    submitted = dt.datetime.fromisoformat(
        created["submitted_at"].replace("Z", "+00:00")
    )
    expires = dt.datetime.fromisoformat(
        created["artifacts_expire_at"].replace("Z", "+00:00")
    )
    assert expires - submitted == dt.timedelta(days=7)
    assert artifact["expires_at"] == created["artifacts_expire_at"]


def test_quick_load_submission_cleans_created_files_when_artifact_insert_fails(
    tmp_path,
):
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "CREATE TRIGGER reject_input_artifact BEFORE INSERT ON operation_artifacts "
            "BEGIN SELECT RAISE(FAIL, 'artifact insert failed'); END"
        )
    source = tmp_path / "vendor.mrc"
    source.write_bytes(sample_mrc_bytes())
    unrelated = operations.operations_root() / "unrelated" / "keep.mrc"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"unrelated")

    with pytest.raises(Exception, match="artifact insert failed"):
        operation_submission.submit_quick_load_task_run(
            user_email="owner@smith.edu",
            source_path=source,
            filename="vendor.mrc",
            record_count=2,
            task_specs=[_task()],
        )

    assert unrelated.read_bytes() == b"unrelated"
    assert list(operations.operations_root().rglob("*.mrc")) == [unrelated]
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
