"""Tests for server-side job/project helpers (TASK-081)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import db, jobs, upload_persistence


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


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


def test_record_upload_attaches_to_default_job():
    upload_persistence.record_upload(
        user="alice@example.edu",
        filename="load.mrc",
        file_path="/tmp/load.mrc",
        record_count=2,
        file_bytes=100,
    )

    row = upload_persistence.get_active_upload("alice@example.edu")
    default_job = jobs.ensure_default_job("alice@example.edu")

    assert row["job_id"] == default_job["id"]


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


def test_list_job_summaries_includes_file_and_open_note_counts():
    """Jobs page needs scannable workspace metadata without page-level SQL."""
    job = jobs.create_job("owner@example.edu", "Vendor load July")
    upload_persistence.record_upload(
        user="owner@example.edu",
        filename="vendor.mrc",
        file_path="/tmp/vendor.mrc",
        record_count=12,
        file_bytes=345,
        job_id=job["id"],
    )
    jobs.add_review_note(
        job["id"],
        anchor_kind="record",
        anchor_value="7",
        note="Check 856 proxy.",
        author="owner@example.edu",
    )

    rows = jobs.list_job_summaries("owner@example.edu")

    assert rows == [
        {
            "id": job["id"],
            "name": "Vendor load July",
            "owner_email": "owner@example.edu",
            "access_role": "owner",
            "status": jobs.STATUS_ACTIVE,
            "active": 1,
            "file_count": 1,
            "open_note_count": 1,
            "updated_at": job["updated_at"],
        }
    ]


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
    assert jobs.list_review_notes(job["id"], include_resolved=False) == []
    assert jobs.list_activity(
        job["id"], user_email="owner@example.edu"
    )[-1]["kind"] == "note-resolved"


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
