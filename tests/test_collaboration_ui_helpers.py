"""Pure helper tests for collaboration edit UI gates (TASK-095)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import db, jobs, locks
from marcedit_web.render import fixed_field_helper
from marcedit_web.render import single_record_edit


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def test_can_edit_record_requires_editor_or_owner_and_lock_holder():
    assert single_record_edit._can_edit_record("owner", True) is True
    assert single_record_edit._can_edit_record("editor", True) is True
    assert single_record_edit._can_edit_record("viewer", True) is False
    assert single_record_edit._can_edit_record("editor", False) is False
    assert single_record_edit._can_edit_record(None, True) is False


def test_record_lock_state_ignores_expired_locks(monkeypatch):
    job = jobs.create_job("owner@example.edu", "Shared load")
    locks.acquire_lock(
        "record",
        single_record_edit.collaboration.record_resource_id(job["id"], 1),
        "other@example.edu",
        ttl_seconds=-1,
    )
    monkeypatch.setattr(
        single_record_edit.session,
        "current_user_id",
        lambda: "owner@example.edu",
    )

    row, holds_lock = single_record_edit._record_lock_state(job["id"], 1)

    assert row is None
    assert holds_lock is False


def test_checkout_version_key_is_shared_per_job_record():
    _, first_version = single_record_edit._checkout_keys("view_edit", 7, 42)
    _, second_version = single_record_edit._checkout_keys("view_control", 7, 42)

    assert first_version == second_version


def test_fixed_save_gate_blocks_viewer(monkeypatch):
    monkeypatch.setattr(fixed_field_helper.st, "session_state", {"current_job_id": 1})
    monkeypatch.setattr(
        fixed_field_helper.session,
        "current_user_id",
        lambda: "viewer@example.edu",
    )
    monkeypatch.setattr(
        fixed_field_helper.jobs,
        "get_access_role",
        lambda job_id, user: "viewer",
    )
    monkeypatch.setattr(
        fixed_field_helper.single_record_edit,
        "_record_lock_state",
        lambda job_id, index: (None, True),
    )

    disabled, message = fixed_field_helper._fixed_save_gate(1)

    assert disabled is True
    assert "read-only" in message


def test_fixed_save_assertion_requires_opened_version(monkeypatch):
    errors = []
    monkeypatch.setattr(fixed_field_helper.st, "session_state", {"current_job_id": 1})
    monkeypatch.setattr(fixed_field_helper.st, "error", errors.append)
    monkeypatch.setattr(
        fixed_field_helper.session,
        "current_user_id",
        lambda: "owner@example.edu",
    )
    monkeypatch.setattr(
        fixed_field_helper.jobs,
        "get_access_role",
        lambda job_id, user: "owner",
    )
    monkeypatch.setattr(
        fixed_field_helper.single_record_edit,
        "_record_lock_state",
        lambda job_id, index: ({"holder_email": "owner@example.edu"}, True),
    )

    assert fixed_field_helper._assert_fixed_save_allowed(1, "view_control") is False
    assert "checkout is missing" in errors[0]
