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


def test_should_open_editor_immediately_honors_existing_state():
    session_state = {"workspace_edit_active": False}

    assert single_record_edit._should_open_immediately(
        session_state,
        "workspace_edit_active",
        start_open=True,
    ) is True
    assert single_record_edit._should_open_immediately(
        session_state,
        "workspace_edit_active",
        start_open=False,
    ) is False


def test_should_open_editor_immediately_does_not_reopen_after_cancel():
    session_state = {
        "workspace_edit_active": False,
        "workspace_edit_user_closed": True,
    }

    assert single_record_edit._should_open_immediately(
        session_state,
        "workspace_edit_active",
        start_open=True,
    ) is False


def test_should_show_pending_preview_uses_session_state_flag():
    assert single_record_edit._should_show_pending_preview(
        {"workspace_edit_pending_preview": True},
        "workspace_edit_pending_preview",
    ) is True
    assert single_record_edit._should_show_pending_preview(
        {},
        "workspace_edit_pending_preview",
    ) is False


def test_pending_preview_opens_dialog(monkeypatch):
    opened = []
    monkeypatch.setattr(
        single_record_edit,
        "_record_save_preview_dialog",
        lambda **kwargs: opened.append(kwargs),
    )

    single_record_edit._open_pending_preview_dialog(
        draft=object(),
        live_result=object(),
        key_prefix="workspace_edit",
        index=2,
        save_callback=lambda status_col: None,
        dismiss_callback=lambda: None,
    )

    assert opened[0]["index"] == 2
    assert callable(opened[0]["save_callback"])
    assert callable(opened[0]["dismiss_callback"])


def test_floating_jump_rail_html_is_fixed_and_collapsible():
    html = single_record_edit._floating_jump_rail_html([
        ("fixed", "Leader / control fields"),
        ("245", "245 Title"),
    ])

    assert "position: fixed" in html
    assert "<details" in html
    assert "<summary" in html
    assert 'href="#record-field-fixed"' in html
    assert 'href="#record-field-245"' in html
    assert "Leader / control fields" in html
    assert "padding-right: 13rem" in html


def test_clear_export_payloads_removes_only_matching_editor_keys():
    session_state = {
        "workspace_edit_export_payload_1": (b"old", "old.mrc"),
        "view_edit_export_payload_1": (b"keep", "keep.mrc"),
        "workspace_edit_active": True,
    }

    single_record_edit._clear_export_payloads(session_state, "workspace_edit")

    assert "workspace_edit_export_payload_1" not in session_state
    assert session_state["view_edit_export_payload_1"] == (b"keep", "keep.mrc")
    assert session_state["workspace_edit_active"] is True


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
