"""End-to-end job-file export workflow tests for TASK-151.

Exports are delivery evidence, so their bytes and labels must remain bound to
one immutable version even as later file work continues.
"""

from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from marcedit_web.lib import collaboration, db, job_files, jobs


OWNER = "owner@example.edu"
EDITOR = "editor@example.edu"
VIEWER = "viewer@example.edu"


@pytest.fixture(autouse=True)
def _isolated_job_files_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))


@pytest.fixture
def checked_out_file():
    source = Path("tests/fixtures/sample.mrc")
    job = jobs.create_job(OWNER, "Routledge")
    jobs.grant_access(job["id"], EDITOR, "editor", by=OWNER)
    jobs.grant_access(job["id"], VIEWER, "viewer", by=OWNER)
    attached = job_files.attach_file(
        job_id=job["id"],
        user_email=OWNER,
        source_path=source,
        filename="Routledge deletes.mrc",
        record_count=7,
        file_bytes=source.stat().st_size,
    )
    collaboration.acquire_file_checkout(attached["id"], OWNER)
    return attached


@pytest.fixture
def approved_checked_out_file(checked_out_file):
    return job_files.approve_current(
        checked_out_file["id"],
        by=OWNER,
        opened_version_id=checked_out_file["current_version_id"],
    )


@pytest.fixture
def ready_export(approved_checked_out_file):
    return job_files.create_export(
        file_id=approved_checked_out_file["id"],
        opened_version_id=approved_checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="EDS deletion load",
        description="July Routledge withdrawal",
    )


def test_export_from_approved_current_version_is_ready(
    approved_checked_out_file,
):
    """Only an approved exact current version is ready for an external load."""
    current = job_files.get_current_version(approved_checked_out_file["id"], OWNER)

    export = job_files.create_export(
        file_id=approved_checked_out_file["id"],
        opened_version_id=current["id"],
        user_email=OWNER,
        purpose="EDS deletion load",
        description="July Routledge withdrawal",
    )

    assert export["state"] == "ready"
    assert export["version_id"] == current["id"]
    assert Path(export["file_path"]).read_bytes() == Path(
        current["file_path"]
    ).read_bytes()
    assert Path(export["file_path"]).parent.name == "exports"
    assert job_files.get_file(export["job_file_id"], OWNER)["status"] == "exported"


def test_unapproved_export_is_retained_as_visibly_distinct_draft(checked_out_file):
    """A useful artifact must not imply load approval that never happened."""
    export = job_files.create_export(
        file_id=checked_out_file["id"],
        opened_version_id=checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="Review copy",
        filename="../../draft copy.mrc",
    )

    assert export["state"] == "draft"
    assert export["filename"] == "draft-copy.mrc"
    assert job_files.get_file(checked_out_file["id"], OWNER)["status"] == "in_progress"


@pytest.mark.parametrize("purpose", ["", "  \t"])
def test_export_requires_a_nonblank_purpose(checked_out_file, purpose):
    with pytest.raises(job_files.JobFileError, match="purpose"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=OWNER,
            purpose=purpose,
        )

    assert not (job_files.versions_root() / str(checked_out_file["id"]) / "exports").exists()


def test_export_rechecks_exact_version_and_checkout_before_copying(checked_out_file):
    """A stale tab cannot label or retain bytes from a newer current version."""
    with pytest.raises(job_files.JobFileError, match="changed"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=int(checked_out_file["current_version_id"]) + 1,
            user_email=OWNER,
            purpose="EDS load",
        )

    collaboration.release_file_checkout(checked_out_file["id"], OWNER)
    with pytest.raises(job_files.JobFileError, match="checkout"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=OWNER,
            purpose="EDS load",
        )
    assert job_files.list_exports(checked_out_file["id"], OWNER) == []


def test_failed_export_copy_removes_partial_artifact_and_database_row(
    checked_out_file, monkeypatch,
):
    """A failed copy must not leave an unlabeled file that looks retained."""
    def fail_after_partial_copy(source, target, *_args):
        target.write(source.read(16))
        raise OSError("disk full")

    monkeypatch.setattr(job_files.shutil, "copyfileobj", fail_after_partial_copy)

    with pytest.raises(OSError, match="disk full"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=OWNER,
            purpose="EDS load",
        )

    export_dir = job_files.versions_root() / str(checked_out_file["id"]) / "exports"
    assert list(export_dir.iterdir()) == []
    assert job_files.list_exports(checked_out_file["id"], OWNER) == []


def test_export_rechecks_checkout_after_slow_validation(
    checked_out_file, monkeypatch,
):
    """A lease expiring during MARC validation cannot authorize insertion."""
    before = job_files.get_file(checked_out_file["id"], OWNER)
    with db.connect() as conn:
        activity_before = conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE job_file_id=?",
            (checked_out_file["id"],),
        ).fetchone()[0]
    first_check = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    checks = iter((first_check, first_check + dt.timedelta(hours=1)))
    monkeypatch.setattr(collaboration, "_now", lambda: next(checks))

    with pytest.raises(job_files.JobFileError, match="checkout"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=OWNER,
            purpose="EDS load",
        )

    after = job_files.get_file(checked_out_file["id"], OWNER)
    assert after["status"] == before["status"]
    assert after["current_version_id"] == before["current_version_id"]
    assert job_files.list_exports(checked_out_file["id"], OWNER) == []
    export_dir = job_files.versions_root() / str(checked_out_file["id"]) / "exports"
    assert list(export_dir.iterdir()) == []
    with db.connect() as conn:
        activity_after = conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE job_file_id=?",
            (checked_out_file["id"],),
        ).fetchone()[0]
    assert activity_after == activity_before


def test_uuid_collision_never_overwrites_referenced_export(
    checked_out_file, monkeypatch,
):
    """Filesystem exclusivity protects retained evidence before SQL insertion."""
    first = job_files.create_export(
        file_id=checked_out_file["id"],
        opened_version_id=checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="First review copy",
    )
    first_path = Path(first["file_path"])
    first_path.write_bytes(b"retained-original-evidence")
    first_uuid = first_path.name.split("-", 1)[0]
    generated = iter((first_uuid, "f" * 32))
    monkeypatch.setattr(
        job_files.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=next(generated)),
    )

    second = job_files.create_export(
        file_id=checked_out_file["id"],
        opened_version_id=checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="Second review copy",
    )

    assert Path(second["file_path"]) != first_path
    assert first_path.read_bytes() == b"retained-original-evidence"
    assert job_files.get_export(first["id"], OWNER)["file_path"] == str(first_path)
    assert len(job_files.list_exports(checked_out_file["id"], OWNER)) == 2


def test_copy_source_failure_cannot_delete_colliding_referenced_export(
    checked_out_file, monkeypatch,
):
    """Cleanup owns only a path that this export attempt created exclusively."""
    first = job_files.create_export(
        file_id=checked_out_file["id"],
        opened_version_id=checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="Retained evidence",
    )
    first_path = Path(first["file_path"])
    retained_bytes = first_path.read_bytes()
    source = job_files.get_current_version(checked_out_file["id"], OWNER)
    Path(source["file_path"]).unlink()
    collision_uuid = first_path.name.split("-", 1)[0]
    monkeypatch.setattr(
        job_files.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=collision_uuid),
    )

    with pytest.raises(job_files.JobFileError, match="unique export path"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=OWNER,
            purpose="Failed copy",
        )

    assert first_path.read_bytes() == retained_bytes
    assert job_files.get_export(first["id"], OWNER)["file_path"] == str(first_path)


def test_mark_loaded_does_not_require_checkout_and_preserves_bytes(ready_export):
    """A manual downstream acknowledgement is an audit action, not editing."""
    artifact = Path(ready_export["file_path"])
    before = artifact.read_bytes()
    collaboration.release_file_checkout(ready_export["job_file_id"], OWNER)

    loaded = job_files.mark_export_loaded(
        ready_export["id"],
        by=EDITOR,
        destination="EDS",
        external_id="load-2026-07-14",
        note="Accepted by EDS",
    )

    assert loaded["state"] == "loaded"
    assert loaded["loaded_by"] == EDITOR
    assert loaded["loaded_destination"] == "EDS"
    assert loaded["loaded_external_id"] == "load-2026-07-14"
    assert loaded["loaded_note"] == "Accepted by EDS"
    assert loaded["loaded_at"] is not None
    assert artifact.read_bytes() == before
    assert job_files.get_file(ready_export["job_file_id"], OWNER)["status"] == "exported"


def test_mark_loaded_requires_destination_and_editor_access(ready_export):
    with pytest.raises(job_files.JobFileError, match="destination"):
        job_files.mark_export_loaded(ready_export["id"], by=EDITOR, destination=" ")
    with pytest.raises(job_files.JobFileError, match="owner or editor"):
        job_files.mark_export_loaded(ready_export["id"], by=VIEWER, destination="EDS")

    assert job_files.get_export(ready_export["id"], OWNER)["state"] == "ready"


def test_later_version_supersedes_unloaded_export_but_not_loaded_export(
    approved_checked_out_file, ready_export, tmp_path,
):
    """Prior delivery evidence survives while obsolete candidates are labeled."""
    loaded = job_files.create_export(
        file_id=approved_checked_out_file["id"],
        opened_version_id=approved_checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="EDS confirmed load",
    )
    loaded = job_files.mark_export_loaded(
        loaded["id"], by=OWNER, destination="EDS"
    )
    loaded_bytes = Path(loaded["file_path"]).read_bytes()
    candidate = tmp_path / "candidate.mrc"
    shutil.copyfile("tests/fixtures/sample.mrc", candidate)

    adopted = job_files.adopt_candidate(
        file_id=approved_checked_out_file["id"],
        opened_version_id=approved_checked_out_file["current_version_id"],
        user_email=OWNER,
        candidate_path=candidate,
        source_kind="task",
        label="Later cleanup",
    )

    superseded = job_files.get_export(ready_export["id"], OWNER)
    assert superseded["state"] == "superseded"
    assert superseded["superseded_by_version_id"] == adopted["id"]
    assert job_files.get_export(loaded["id"], OWNER)["state"] == "loaded"
    assert Path(loaded["file_path"]).read_bytes() == loaded_bytes


def test_viewer_can_read_retained_exports_but_cannot_create_one(checked_out_file):
    export = job_files.create_export(
        file_id=checked_out_file["id"],
        opened_version_id=checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="Review copy",
    )

    assert job_files.get_export(export["id"], VIEWER)["purpose"] == "Review copy"
    assert [row["id"] for row in job_files.list_exports(
        checked_out_file["id"], VIEWER
    )] == [export["id"]]
    with pytest.raises(job_files.JobFileError, match="owner or editor"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=VIEWER,
            purpose="Unauthorized copy",
        )


def test_draft_or_superseded_export_cannot_be_marked_loaded(checked_out_file):
    draft = job_files.create_export(
        file_id=checked_out_file["id"],
        opened_version_id=checked_out_file["current_version_id"],
        user_email=OWNER,
        purpose="Review copy",
    )

    with pytest.raises(job_files.JobFileError, match="ready"):
        job_files.mark_export_loaded(draft["id"], by=OWNER, destination="EDS")

    with db.connect() as conn:
        conn.execute(
            "UPDATE job_file_exports SET state='superseded' WHERE id=?",
            (draft["id"],),
        )
    with pytest.raises(job_files.JobFileError, match="ready"):
        job_files.mark_export_loaded(draft["id"], by=OWNER, destination="EDS")


def _fail_first_connection_commit(monkeypatch, *, persist_before_raise):
    original_connect = db.connect
    first = True

    @contextmanager
    def failing_connect():
        nonlocal first
        if not first:
            with original_connect() as conn:
                yield conn
            return
        first = False
        conn = sqlite3.connect(db.db_path(), isolation_level="DEFERRED")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            if persist_before_raise:
                conn.commit()
                raise RuntimeError("commit persisted but confirmation failed")
            raise RuntimeError("commit failed before persistence")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(db, "connect", failing_connect)


def test_export_commit_failure_before_persistence_cleans_unreferenced_bytes(
    checked_out_file, monkeypatch,
):
    """A rolled-back export must leave neither delivery evidence nor activity."""
    before = job_files.get_file(checked_out_file["id"], OWNER)
    with db.connect() as conn:
        activity_before = conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE job_file_id=?",
            (checked_out_file["id"],),
        ).fetchone()[0]
    _fail_first_connection_commit(monkeypatch, persist_before_raise=False)

    with pytest.raises(RuntimeError, match="failed before persistence"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=OWNER,
            purpose="EDS load",
        )

    assert job_files.list_exports(checked_out_file["id"], OWNER) == []
    assert (
        job_files.get_file(checked_out_file["id"], OWNER)["status"]
        == before["status"]
    )
    export_dir = job_files.versions_root() / str(checked_out_file["id"]) / "exports"
    assert list(export_dir.iterdir()) == []
    with db.connect() as conn:
        activity_after = conn.execute(
            "SELECT COUNT(*) FROM job_activity WHERE job_file_id=?",
            (checked_out_file["id"],),
        ).fetchone()[0]
    assert activity_after == activity_before


def test_export_commit_persisted_then_raised_retains_row_and_bytes(
    checked_out_file, monkeypatch,
):
    """Uncertain transaction exit must preserve any artifact SQL references."""
    source = job_files.get_current_version(checked_out_file["id"], OWNER)
    _fail_first_connection_commit(monkeypatch, persist_before_raise=True)

    with pytest.raises(job_files.JobFileError, match="confirmation failed"):
        job_files.create_export(
            file_id=checked_out_file["id"],
            opened_version_id=checked_out_file["current_version_id"],
            user_email=OWNER,
            purpose="EDS load",
        )

    exports = job_files.list_exports(checked_out_file["id"], OWNER)
    assert len(exports) == 1
    assert Path(exports[0]["file_path"]).read_bytes() == Path(
        source["file_path"]
    ).read_bytes()


def test_routledge_job_handles_deletion_and_fresh_files_independently(tmp_path):
    """The cataloger handoff keeps two Routledge deliverables fully separate."""
    source = Path("tests/fixtures/sample.mrc")
    job = jobs.create_job(OWNER, "Routledge load")
    jobs.grant_access(job["id"], EDITOR, "editor", by=OWNER)

    deletion = job_files.attach_file(
        job_id=job["id"],
        user_email=OWNER,
        source_path=source,
        filename="current-routledge.mrc",
        record_count=7,
        file_bytes=source.stat().st_size,
    )
    assert collaboration.acquire_file_checkout(deletion["id"], OWNER).acquired
    deletion_candidate = tmp_path / "deletion-candidate.mrc"
    shutil.copyfile(source, deletion_candidate)
    deletion_version = job_files.adopt_candidate(
        file_id=deletion["id"],
        opened_version_id=deletion["current_version_id"],
        user_email=OWNER,
        candidate_path=deletion_candidate,
        source_kind="quick-batch",
        label="Set leader record status to deleted",
    )
    job_files.return_for_review(
        deletion["id"],
        OWNER,
        opened_version_id=deletion_version["id"],
    )
    assert collaboration.acquire_file_checkout(deletion["id"], EDITOR).acquired
    job_files.approve_current(
        deletion["id"],
        EDITOR,
        opened_version_id=deletion_version["id"],
    )
    deletion_note = jobs.add_review_note(
        job["id"],
        anchor_kind="job_file",
        note="Deletion file approved for EDS.",
        author=EDITOR,
        job_file_id=deletion["id"],
        job_file_version_id=deletion_version["id"],
    )
    deletion_export = job_files.create_export(
        file_id=deletion["id"],
        opened_version_id=deletion_version["id"],
        user_email=EDITOR,
        purpose="EDS deletion load",
    )
    loaded_deletion = job_files.mark_export_loaded(
        deletion_export["id"],
        by=OWNER,
        destination="EDS",
    )

    fresh = job_files.attach_file(
        job_id=job["id"],
        user_email=OWNER,
        source_path=source,
        filename="fresh-routledge.mrc",
        record_count=7,
        file_bytes=source.stat().st_size,
    )
    assert collaboration.acquire_file_checkout(fresh["id"], OWNER).acquired
    fresh_candidate = tmp_path / "fresh-candidate.mrc"
    shutil.copyfile(source, fresh_candidate)
    fresh_version = job_files.adopt_candidate(
        file_id=fresh["id"],
        opened_version_id=fresh["current_version_id"],
        user_email=OWNER,
        candidate_path=fresh_candidate,
        source_kind="task",
        label="Routledge normalization",
    )
    job_files.return_for_review(
        fresh["id"],
        OWNER,
        opened_version_id=fresh_version["id"],
    )
    assert collaboration.acquire_file_checkout(fresh["id"], OWNER).acquired
    job_files.approve_current(
        fresh["id"],
        OWNER,
        opened_version_id=fresh_version["id"],
    )
    fresh_note = jobs.add_review_note(
        job["id"],
        anchor_kind="job_file",
        note="Replacement file normalized and self-approved.",
        author=OWNER,
        job_file_id=fresh["id"],
        job_file_version_id=fresh_version["id"],
    )
    replacement_export = job_files.create_export(
        file_id=fresh["id"],
        opened_version_id=fresh_version["id"],
        user_email=OWNER,
        purpose="EDS replacement load",
    )

    assert deletion["id"] != fresh["id"]
    assert job_files.get_file(deletion["id"], OWNER)["status"] == "exported"
    assert job_files.get_file(fresh["id"], OWNER)["status"] == "exported"
    assert loaded_deletion["state"] == "loaded"
    assert replacement_export["state"] == "ready"
    assert deletion_export["version_id"] != replacement_export["version_id"]
    assert [row["version_number"] for row in job_files.list_versions(
        deletion["id"], OWNER
    )] == [1, 2]
    assert [row["version_number"] for row in job_files.list_versions(
        fresh["id"], OWNER
    )] == [1, 2]
    assert job_files.get_version(deletion_version["id"], OWNER)[
        "approval_kind"
    ] == "peer-approved"
    assert job_files.get_version(fresh_version["id"], OWNER)[
        "approval_kind"
    ] == "self-approved"
    assert [row["id"] for row in jobs.list_review_notes(
        job["id"], user_email=OWNER, job_file_id=deletion["id"]
    )] == [deletion_note["id"]]
    assert [row["id"] for row in jobs.list_review_notes(
        job["id"], user_email=OWNER, job_file_id=fresh["id"]
    )] == [fresh_note["id"]]
    activity_file_ids = {
        row["job_file_id"]
        for row in jobs.list_activity(job["id"], user_email=OWNER)
        if row["job_file_id"] is not None
    }
    assert {deletion["id"], fresh["id"]}.issubset(activity_file_ids)
