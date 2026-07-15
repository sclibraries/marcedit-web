"""End-to-end job-file export workflow tests for TASK-151.

Exports are delivery evidence, so their bytes and labels must remain bound to
one immutable version even as later file work continues.
"""

from __future__ import annotations

import shutil
from pathlib import Path

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
    def fail_after_partial_copy(source, target):
        Path(target).write_bytes(Path(source).read_bytes()[:16])
        raise OSError("disk full")

    monkeypatch.setattr(job_files.shutil, "copyfile", fail_after_partial_copy)

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
