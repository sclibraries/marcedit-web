"""Tests for server-side job/project helpers (TASK-081)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import db, job_files, jobs, upload_persistence


@pytest.fixture(autouse=True)
def _schema(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))
    db.init_schema()


def attach_job_file(job, tmp_path, filename):
    source = tmp_path / filename
    source.write_bytes(b"x")
    return job_files.attach_file(
        job_id=job["id"],
        user_email="owner@example.edu",
        source_path=source,
        filename=filename,
        record_count=1,
        file_bytes=1,
    )


def test_ensure_default_job_is_idempotent():
    """Every user gets one stable personal job for legacy/default uploads."""
    first = jobs.ensure_default_job("alice@example.edu")
    second = jobs.ensure_default_job("alice@example.edu")

    assert second["id"] == first["id"]
    assert first["name"] == "Personal uploads"
    assert first["owner_email"] == "alice@example.edu"
    assert first["visibility"] == "private"


def test_create_and_list_named_jobs():
    """Users can create named server-side jobs before sharing UI exists."""
    created = jobs.create_job("alice@example.edu", "Vendor load June")

    listed = jobs.list_jobs("alice@example.edu")

    assert created["name"] == "Vendor load June"
    assert [job["name"] for job in listed] == ["Vendor load June"]


def test_create_job_rejects_duplicate_owner_name():
    jobs.create_job("alice@example.edu", "Vendor load June")

    with pytest.raises(jobs.JobError):
        jobs.create_job("alice@example.edu", "Vendor load June")


def test_owner_can_grant_and_revoke_shared_job_access():
    job = jobs.create_job("owner@example.edu", "Shared load")

    granted = jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )

    assert granted["job_id"] == job["id"]
    assert granted["user_email"] == "editor@example.edu"
    assert granted["role"] == "editor"
    assert jobs.get_access_role(job["id"], "editor@example.edu") == "editor"
    assert jobs.revoke_access(
        job["id"],
        "editor@example.edu",
        by="owner@example.edu",
    ) is True
    assert jobs.get_access_role(job["id"], "editor@example.edu") is None


def test_non_owner_cannot_grant_shared_job_access():
    job = jobs.create_job("owner@example.edu", "Shared load")

    with pytest.raises(jobs.JobError, match="owner"):
        jobs.grant_access(
            job["id"],
            "editor@example.edu",
            "editor",
            by="not-owner@example.edu",
        )


def test_owner_role_cannot_be_downgraded_by_grant():
    job = jobs.create_job("owner@example.edu", "Shared load")

    with pytest.raises(jobs.JobError, match="owner access"):
        jobs.grant_access(
            job["id"],
            "owner@example.edu",
            "viewer",
            by="owner@example.edu",
        )

    assert jobs.get_access_role(job["id"], "owner@example.edu") == "owner"


def test_list_jobs_includes_shared_jobs_with_role():
    owned = jobs.create_job("alice@example.edu", "Owned")
    shared = jobs.create_job("owner@example.edu", "Shared")
    jobs.grant_access(
        shared["id"],
        "alice@example.edu",
        "viewer",
        by="owner@example.edu",
    )

    rows = jobs.list_jobs("alice@example.edu")

    assert [(row["id"], row["access_role"]) for row in rows] == [
        (owned["id"], "owner"),
        (shared["id"], "viewer"),
    ]


def test_require_role_returns_matching_role_and_rejects_viewer():
    job = jobs.create_job("owner@example.edu", "Shared load")
    jobs.grant_access(
        job["id"],
        "viewer@example.edu",
        "viewer",
        by="owner@example.edu",
    )

    assert jobs.require_role(
        job["id"], "owner@example.edu", {"owner", "editor"}
    ) == "owner"
    with pytest.raises(jobs.JobError, match="access denied"):
        jobs.require_role(
            job["id"], "viewer@example.edu", {"owner", "editor"}
        )


def test_record_upload_without_explicit_job_remains_unassigned():
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="load.mrc",
        file_path="/tmp/load.mrc",
        record_count=2,
        file_bytes=100,
    )

    row = upload_persistence.get_active_upload("alice@example.edu")

    assert row["job_id"] is None


def test_record_upload_can_attach_to_named_job():
    job = jobs.create_job("alice@example.edu", "Vendor load June")

    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="load.mrc",
        file_path="/tmp/load.mrc",
        record_count=2,
        file_bytes=100,
        job_id=job["id"],
    )

    row = upload_persistence.get_active_upload("alice@example.edu")
    assert row["job_id"] == job["id"]


def test_list_job_uploads_returns_all_files_for_job():
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="first.mrc",
        file_path="/tmp/first.mrc",
        record_count=2,
        file_bytes=100,
        job_id=job["id"],
    )
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="second.mrc",
        file_path="/tmp/second.mrc",
        record_count=3,
        file_bytes=200,
        job_id=job["id"],
    )

    uploads = jobs.list_job_uploads(job["id"])

    assert [row["filename"] for row in uploads] == ["first.mrc", "second.mrc"]


def test_remove_upload_hides_file_without_deleting_bytes(tmp_path):
    """Normal removal detaches a file from the job list but preserves bytes."""
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    path = tmp_path / "vendor.mrc"
    path.write_bytes(b"marc")
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="vendor.mrc",
        file_path=path,
        record_count=2,
        file_bytes=100,
        job_id=job["id"],
    )
    upload = jobs.list_job_uploads(job["id"])[0]

    jobs.remove_upload(upload["id"], by="alice@example.edu")

    assert jobs.list_job_uploads(job["id"]) == []
    assert path.exists()
    removed = jobs.list_job_uploads(job["id"], include_removed=True)
    assert [row["filename"] for row in removed] == ["vendor.mrc"]


def test_delete_upload_file_requires_original_uploader(tmp_path):
    """Hard deletion is explicit and limited to the cataloger who uploaded it."""
    job = jobs.create_job("alice@example.edu", "Vendor load June")
    jobs.grant_access(job["id"], "bob@example.edu", "editor", by="alice@example.edu")
    path = tmp_path / "vendor.mrc"
    path.write_bytes(b"marc")
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="vendor.mrc",
        file_path=path,
        record_count=2,
        file_bytes=100,
        job_id=job["id"],
    )
    upload = jobs.list_job_uploads(job["id"])[0]

    with pytest.raises(jobs.JobError, match="original uploader"):
        jobs.remove_upload(upload["id"], by="bob@example.edu", delete_file=True)

    assert path.exists()

    jobs.remove_upload(upload["id"], by="alice@example.edu", delete_file=True)

    assert not path.exists()


def test_new_job_defaults_to_active_status():
    """New shared workspaces begin as active, not review-blocked."""
    created = jobs.create_job("alice@example.edu", "Vendor load July")

    assert created["status"] == jobs.STATUS_ACTIVE
    assert created["active"] == 1


def test_owner_or_editor_can_change_job_status_and_activity_records_it():
    """Review status is coordination metadata with an auditable trail."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )

    updated = jobs.set_status(
        job["id"],
        jobs.STATUS_NEEDS_REVIEW,
        by="editor@example.edu",
        note="Please check 856 proxy prefixes.",
    )

    assert updated["status"] == jobs.STATUS_NEEDS_REVIEW
    activity = jobs.list_activity(job["id"], user_email="editor@example.edu")
    assert activity[-1]["kind"] == "status-changed"
    assert activity[-1]["actor_email"] == "editor@example.edu"
    assert "Please check 856 proxy prefixes." in activity[-1]["message"]


def test_viewer_cannot_change_job_status():
    """Viewers may inspect review state but cannot move the workflow."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    jobs.grant_access(
        job["id"],
        "viewer@example.edu",
        "viewer",
        by="owner@example.edu",
    )

    with pytest.raises(jobs.JobError, match="access denied"):
        jobs.set_status(
            job["id"],
            jobs.STATUS_APPROVED,
            by="viewer@example.edu",
        )


def test_archive_is_owner_only_and_hides_job_from_active_list():
    """Archive is a reversible soft delete that preserves history."""
    job = jobs.create_job("owner@example.edu", "Old vendor load")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )

    with pytest.raises(jobs.JobError, match="owner"):
        jobs.archive_job(job["id"], by="editor@example.edu")

    archived = jobs.archive_job(job["id"], by="owner@example.edu")

    assert archived["active"] == 0
    assert archived["status"] == jobs.STATUS_ARCHIVED
    assert [row["id"] for row in jobs.list_jobs("owner@example.edu")] == []
    assert jobs.get_job(job["id"])["id"] == job["id"]


def test_default_personal_uploads_job_cannot_be_archived():
    """Quick Load needs a permanent default job target."""
    default = jobs.ensure_default_job("alice@example.edu")

    with pytest.raises(jobs.JobError, match="Personal uploads"):
        jobs.archive_job(default["id"], by="alice@example.edu")


def test_archived_job_status_can_only_change_via_owner_restore():
    """Archived jobs stay archived until the owner explicitly restores them."""
    job = jobs.create_job("owner@example.edu", "Old vendor load")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )
    jobs.archive_job(job["id"], by="owner@example.edu")

    with pytest.raises(jobs.JobError, match="restore"):
        jobs.set_status(
            job["id"],
            jobs.STATUS_APPROVED,
            by="editor@example.edu",
        )

    archived = jobs.get_job(job["id"])
    assert archived["active"] == 0
    assert archived["status"] == jobs.STATUS_ARCHIVED


def test_list_activity_requires_membership_but_allows_viewers():
    """Activity is visible to job members, including viewers, but not outsiders."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    jobs.grant_access(
        job["id"],
        "viewer@example.edu",
        "viewer",
        by="owner@example.edu",
    )
    jobs.set_status(
        job["id"],
        jobs.STATUS_NEEDS_REVIEW,
        by="owner@example.edu",
    )

    viewer_rows = jobs.list_activity(job["id"], user_email="viewer@example.edu")

    assert viewer_rows[-1]["kind"] == "status-changed"
    with pytest.raises(jobs.JobError, match="access denied"):
        jobs.list_activity(job["id"], user_email="outsider@example.edu")


def test_restore_job_is_owner_only_and_records_activity():
    """Only the owner may restore an archived job, and the restore is audited."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )
    jobs.archive_job(job["id"], by="owner@example.edu")

    with pytest.raises(jobs.JobError, match="owner"):
        jobs.restore_job(job["id"], by="editor@example.edu")

    restored = jobs.restore_job(job["id"], by="owner@example.edu")

    assert restored["active"] == 1
    assert restored["status"] == jobs.STATUS_ACTIVE
    activity = jobs.list_activity(job["id"], user_email="owner@example.edu")
    assert activity[-1]["kind"] == "job-restored"
    assert activity[-1]["actor_email"] == "owner@example.edu"


def test_list_job_summaries_includes_file_and_open_note_counts(tmp_path):
    """Jobs page needs scannable workspace metadata without page-level SQL."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    attach_job_file(job, tmp_path, "vendor.mrc")
    jobs.add_review_note(
        job["id"],
        anchor_kind="record",
        anchor_value="7",
        note="Check 856 proxy.",
        author="owner@example.edu",
    )

    rows = jobs.list_job_summaries("owner@example.edu")
    current = jobs.get_job(job["id"])

    assert len(rows) == 1
    assert rows[0]["id"] == job["id"]
    assert rows[0]["name"] == "Vendor load July"
    assert rows[0]["owner_email"] == "owner@example.edu"
    assert rows[0]["access_role"] == "owner"
    assert rows[0]["status"] == jobs.STATUS_ACTIVE
    assert rows[0]["active"] == 1
    assert rows[0]["file_count"] == 1
    assert rows[0]["open_note_count"] == 1
    assert rows[0]["updated_at"] == current["updated_at"]
    assert rows[0]["updated_at"]


def test_job_summary_does_not_count_unmaterialized_legacy_upload(tmp_path):
    """A card cannot claim a file that detail cannot render."""
    job = jobs.create_job("owner@example.edu", "Routledge load")
    upload_persistence.record_upload(
        user="owner@example.edu",
        filename="legacy.mrc",
        file_path=str(tmp_path / "legacy.mrc"),
        record_count=1,
        file_bytes=1,
        job_id=job["id"],
    )

    summary = jobs.list_job_summaries("owner@example.edu")[0]

    assert summary["file_count"] == 0


def test_job_summary_count_matches_visible_non_archived_files(tmp_path):
    """Archived files stay hidden from both the card and detail list."""
    job = jobs.create_job("owner@example.edu", "Routledge load")
    visible = attach_job_file(job, tmp_path, "visible.mrc")
    archived = attach_job_file(job, tmp_path, "archived.mrc")
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_files SET archived_at=?,archived_by=? WHERE id=?",
            ("2026-07-22T12:00:00Z", "owner@example.edu", archived["id"]),
        )

    summary = jobs.list_job_summaries("owner@example.edu")[0]
    detail = job_files.list_files(job["id"], "owner@example.edu")

    assert [row["id"] for row in detail] == [visible["id"]]
    assert summary["file_count"] == len(detail) == 1


def test_review_notes_are_record_or_issue_anchored_and_resolvable():
    """Catalogers need ad hoc notes tied to the exact review concern."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    jobs.grant_access(
        job["id"],
        "editor@example.edu",
        "editor",
        by="owner@example.edu",
    )

    note = jobs.add_review_note(
        job["id"],
        anchor_kind="control_number",
        anchor_value="ocn123456",
        note="Confirm provider-neutral fields.",
        author="editor@example.edu",
        category="question",
    )
    resolved = jobs.resolve_review_note(note["id"], by="owner@example.edu")

    assert note["resolved"] == 0
    assert resolved["resolved"] == 1
    assert resolved["resolved_by"] == "owner@example.edu"
    assert (
        jobs.list_review_notes(
            job["id"],
            user_email="owner@example.edu",
            include_resolved=False,
        )
        == []
    )
    assert jobs.list_activity(
        job["id"], user_email="owner@example.edu"
    )[-1]["kind"] == "note-resolved"


def test_viewer_can_read_review_notes_but_outsider_cannot():
    """Review notes are visible to members only, including viewer access."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    note = jobs.add_review_note(
        job["id"],
        anchor_kind="job",
        note="Owner note.",
        author="owner@example.edu",
    )
    jobs.grant_access(
        job["id"],
        "viewer@example.edu",
        "viewer",
        by="owner@example.edu",
    )

    viewer_notes = jobs.list_review_notes(
        job["id"],
        user_email="viewer@example.edu",
    )

    assert [row["id"] for row in viewer_notes] == [note["id"]]
    assert viewer_notes[0]["note"] == "Owner note."
    with pytest.raises(jobs.JobError, match="access denied"):
        jobs.list_review_notes(
            job["id"],
            user_email="outsider@example.edu",
        )


def test_viewer_cannot_add_or_resolve_review_notes():
    """Viewer access is inspect-only for review comments."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    note = jobs.add_review_note(
        job["id"],
        anchor_kind="job",
        note="Owner note.",
        author="owner@example.edu",
    )
    jobs.grant_access(
        job["id"],
        "viewer@example.edu",
        "viewer",
        by="owner@example.edu",
    )

    with pytest.raises(jobs.JobError, match="access denied"):
        jobs.add_review_note(
            job["id"],
            anchor_kind="job",
            note="Viewer note.",
            author="viewer@example.edu",
        )
    with pytest.raises(jobs.JobError, match="access denied"):
        jobs.resolve_review_note(note["id"], by="viewer@example.edu")


def test_review_notes_for_two_files_do_not_mix(tmp_path, monkeypatch):
    """Structured file filters prevent review context leaking across work items."""
    from marcedit_web.lib import job_files

    monkeypatch.setenv(
        "MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files")
    )
    job = jobs.create_job("owner@example.edu", "Routledge")
    attached = []
    for filename, data in (("first.mrc", b"one"), ("second.mrc", b"two")):
        source = tmp_path / filename
        source.write_bytes(data)
        attached.append(job_files.attach_file(
            job_id=job["id"],
            user_email="owner@example.edu",
            source_path=source,
            filename=filename,
            record_count=1,
            file_bytes=len(data),
        ))
    first, second = attached
    jobs.add_review_note(
        job["id"],
        anchor_kind="job_file",
        anchor_value="",
        note="Check leader",
        author="owner@example.edu",
        job_file_id=first["id"],
        job_file_version_id=first["current_version_id"],
    )

    first_notes = jobs.list_review_notes(
        job["id"],
        user_email="owner@example.edu",
        job_file_id=first["id"],
    )
    second_notes = jobs.list_review_notes(
        job["id"],
        user_email="owner@example.edu",
        job_file_id=second["id"],
    )

    assert len(first_notes) == 1
    assert second_notes == []


def test_file_activity_includes_display_name(tmp_path, monkeypatch):
    """Aggregate activity remains understandable when a job has many files."""
    from marcedit_web.lib import collaboration, job_files

    monkeypatch.setenv(
        "MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files")
    )
    job = jobs.create_job("owner@example.edu", "Routledge")
    source = tmp_path / "deletes.mrc"
    source.write_bytes(b"one")
    attached = job_files.attach_file(
        job_id=job["id"],
        user_email="owner@example.edu",
        source_path=source,
        filename=source.name,
        record_count=1,
        file_bytes=3,
    )
    collaboration.acquire_file_checkout(attached["id"], "owner@example.edu")

    job_files.approve_current(
        attached["id"],
        by="owner@example.edu",
        opened_version_id=attached["current_version_id"],
    )

    activity = jobs.list_activity(job["id"], user_email="owner@example.edu")
    assert activity[-1]["job_file_id"] == attached["id"]
    assert "deletes.mrc" in activity[-1]["message"]
