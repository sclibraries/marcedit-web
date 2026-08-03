"""Tasks page mode switcher (TASK-143).

The page previously stacked authoring, running, results, history, and
quick tools in one scroll. These tests pin the new contract: exactly
one mode renders per run, the selection survives reruns via
session_state, and opening the editor forces Build & import so the
editor is never rendered invisibly.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.button_labels = []
        self.clicked_labels = set()
        self.radios: list[dict] = []
        self.dividers = 0
        self.warnings = []
        self.errors = []
        self.successes = []
        self.code_blocks = []
        self.captions = []
        self.rerun_called = False

    def radio(self, label, options, horizontal=False, key=None,
              label_visibility=None):
        self.radios.append(
            {"label": label, "options": tuple(options), "key": key}
        )
        value = self.session_state.get(key)
        if value is None:
            value = options[0]
            self.session_state[key] = value
        return value

    def divider(self):
        self.dividers += 1

    def container(self):
        return self

    def empty(self):
        return self

    def expander(self, label):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def caption(self, value):
        self.captions.append(str(value))

    def warning(self, value):
        self.warnings.append(str(value))

    def markdown(self, value):
        return None

    def error(self, value):
        self.errors.append(str(value))

    def success(self, value):
        self.successes.append(str(value))

    def code(self, value, **kwargs):
        self.code_blocks.append(str(value))

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]

    def button(self, label, **kwargs):
        self.button_labels.append(label)
        return label in self.clicked_labels

    def selectbox(self, label, options, **kwargs):
        return options[0]

    def rerun(self):
        self.rerun_called = True


def _tasks_render(monkeypatch, fake_st):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    return tasks_render


def _wire(monkeypatch, tasks_render, calls):
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.task_admin, "is_admin", lambda user: False
    )
    monkeypatch.setattr(
        tasks_render, "_refresh_tasks_for", lambda user: Path("/tmp/tasks")
    )
    monkeypatch.setattr(
        tasks_render.tasks,
        "load_user_tasks",
        lambda d, force_reload=False: None,
    )
    monkeypatch.setattr(tasks_render.tasks, "all_tasks", lambda: {})
    monkeypatch.setattr(tasks_render, "loaded_batch_status", lambda: None)
    monkeypatch.setattr(
        tasks_render, "_render_run_mode",
        lambda registered, tasks_dir: calls.append("run"),
    )
    monkeypatch.setattr(
        tasks_render, "_render_quick_ops_mode",
        lambda: calls.append("quick"),
    )
    monkeypatch.setattr(
        tasks_render, "_render_build_mode",
        lambda *args: calls.append("build"),
    )


def test_default_mode_is_run_and_only_run(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)

    tasks_render.render()

    assert calls == ["run"]
    assert fake_st.session_state[tasks_render.K_MODE_WIDGET] == (
        tasks_render.MODE_RUN
    )


def test_mode_selection_survives_rerun(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)
    fake_st.session_state[tasks_render.K_MODE_WIDGET] = (
        tasks_render.MODE_QUICK
    )

    tasks_render.render()

    assert calls == ["quick"]


def test_force_mode_overrides_and_clears(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)
    fake_st.session_state[tasks_render.K_MODE_WIDGET] = (
        tasks_render.MODE_RUN
    )
    fake_st.session_state[tasks_render.K_FORCE_MODE] = (
        tasks_render.MODE_BUILD
    )

    tasks_render.render()

    assert calls == ["build"]
    assert tasks_render.K_FORCE_MODE not in fake_st.session_state
    assert fake_st.session_state[tasks_render.K_MODE_WIDGET] == (
        tasks_render.MODE_BUILD
    )


def test_open_editor_for_new_forces_build_mode(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)

    tasks_render._open_editor_for_new()

    assert fake_st.session_state[tasks_render.K_FORCE_MODE] == (
        tasks_render.MODE_BUILD
    )


def test_general_editor_navigation_preserves_pending_import_result(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    pending = {
        "status": "partial",
        "uploaded_filename": "pending.task",
        "imported_task_names": [],
        "entries": [],
        "rejection_category": None,
    }
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = pending

    tasks_render._open_editor_for_new()
    assert fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] == pending

    tasks_render._open_editor_for_existing_row({
        "name": "existing",
        "description": "",
        "body": "pass",
        "visibility": "private",
    }, is_admin=False)
    assert fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] == pending

    tasks_render._cancel_callback()
    assert fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] == pending


def test_new_build_field_defaults_are_structured(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)

    params = tasks_render._default_params_for("build-field")

    assert "subfields" not in params
    assert "if_absent" not in params
    assert params["structured_subfields"] == []
    assert params["existing_field_action"] == "append"
    assert params["missing_control_action"] == "skip_field"


def test_new_guided_find_replace_defaults_match_storage_contract(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)

    assert tasks_render._default_params_for("guided-find-replace") == {
        "target_kind": "subfield",
        "tag": "",
        "subfield": "",
        "match_mode": "contains",
        "find": "",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "",
        "occurrences": "all",
        "value_scope": "all",
        "condition": "always",
    }


def test_existing_legacy_build_is_normalized_in_memory(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    rendered = tasks_render.task_builder.render_ops_to_python(
        [
            tasks_render.Operation(
                kind="build-field",
                params={
                    "tag": "876",
                    "ind1": " ",
                    "ind2": " ",
                    "subfields": [["a", "B({003}){001}-SC"]],
                    "condition": "always",
                    "if_absent": False,
                },
            )
        ]
    )

    tasks_render._open_editor_for_existing_row(
        {
            "name": "legacy-build",
            "description": "",
            "body": rendered["body"],
            "visibility": "private",
        },
        is_admin=False,
    )

    params = fake_st.session_state[tasks_render.K_EDITOR_OPS][0]["params"]
    assert "subfields" not in params
    assert "if_absent" not in params
    assert params["existing_field_action"] == "append"
    assert params["structured_subfields"][0][1][1] == {
        "type": "control_field",
        "tag": "003",
    }


def test_unconvertible_legacy_build_remains_visible_in_memory(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    body = (
        '# OP: build-field {"tag":"876","ind1":" ","ind2":" ",'
        '"subfields":[["a","literal {name}"]],"if_absent":false}\n'
        "pass"
    )

    tasks_render._open_editor_for_existing_row(
        {
            "name": "legacy-braces",
            "description": "",
            "body": body,
            "visibility": "private",
        },
        is_admin=False,
    )

    operation = fake_st.session_state[tasks_render.K_EDITOR_OPS][0]
    assert operation["params"]["subfields"] == [["a", "literal {name}"]]
    assert "cannot convert" in operation["authoring_error"]


def test_invalid_persisted_condition_remains_visible_without_form_coercion(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    body = (
        '# OP: add-field {"tag":"877","ind1":" ","ind2":" ",'
        '"subfields":[["m","Map"]],"condition":"future-condition"}\n'
        "pass"
    )

    tasks_render._open_editor_for_existing_row(
        {
            "name": "future-condition",
            "description": "",
            "body": body,
            "visibility": "private",
        },
        is_admin=False,
    )

    operation = fake_st.session_state[tasks_render.K_EDITOR_OPS][0]
    assert operation["params"]["condition"] == "future-condition"
    assert "record condition" in operation["authoring_error"]


def _wire_compact_form(monkeypatch, tasks_render, calls, *, store=None):
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(tasks_render.task_admin, "is_admin", lambda user: False)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "dialog_contract_error",
        lambda: None,
    )
    monkeypatch.setattr(
        tasks_render.task_operation_reference,
        "open_reference_dialog",
        lambda **kwargs: calls.append(("reference", kwargs)),
    )


def test_form_editor_renders_cards_and_main_actions_without_inline_controls(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operations = [
        {"kind": "delete-tag", "params": {"tag": "029"}},
        {"kind": "guided-find-replace", "params": {"tag": "035"}},
    ]
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = operations
    calls = []
    store = SimpleNamespace(
        count=lambda: 1,
        get=lambda index: (_ for _ in ()).throw(
            AssertionError("compact page must not fetch a preview record")
        ),
    )
    _wire_compact_form(monkeypatch, tasks_render, calls, store=store)
    monkeypatch.setattr(
        tasks_render.task_operation_cards,
        "render_operation_cards",
        lambda ops, **kwargs: calls.append(("cards", list(ops))),
    )
    monkeypatch.setattr(
        tasks_render.task_authoring_render,
        "render_add_field_params",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("controls must not render inline")
        ),
    )

    tasks_render._render_form_editor()

    assert calls == [("cards", operations)]
    assert "+ Add operation" in fake_st.button_labels
    assert "Browse operation reference" in fake_st.button_labels


def test_form_editor_add_opens_transactional_dialog(monkeypatch):
    fake_st = _FakeStreamlit()
    fake_st.clicked_labels.add("+ Add operation")
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = []
    calls = []
    _wire_compact_form(monkeypatch, tasks_render, calls)
    monkeypatch.setattr(
        tasks_render.task_operation_cards,
        "render_operation_cards",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "render_active_dialog",
        lambda state, **kwargs: calls.append(("dialog", state)),
    )

    tasks_render._render_form_editor()

    state = fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE]
    assert state.mode == "add"
    assert state.nonce == 1
    assert calls == [("dialog", state)]


def test_form_editor_card_change_replaces_coordinator_state(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operations = [
        {"kind": "delete-tag", "params": {"tag": "029"}},
        {"kind": "delete-tag", "params": {"tag": "999"}},
    ]
    replacement = [operations[1]]
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = operations
    calls = []
    _wire_compact_form(monkeypatch, tasks_render, calls)

    def render_cards(_ops, **kwargs):
        kwargs["on_change"](replacement)

    monkeypatch.setattr(
        tasks_render.task_operation_cards, "render_operation_cards", render_cards
    )
    tasks_render._render_form_editor()

    assert fake_st.session_state[tasks_render.K_EDITOR_OPS] == replacement
    assert fake_st.session_state[tasks_render.K_EDITOR_OPS] is not replacement
    assert fake_st.rerun_called


def test_form_editor_edit_opens_isolated_transactional_dialog(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operations = [
        {"kind": "delete-tag", "params": {"tag": "029"}},
        {"kind": "delete-tag", "params": {"tag": "999"}},
    ]
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = operations
    calls = []
    _wire_compact_form(monkeypatch, tasks_render, calls)

    def render_cards(_ops, **kwargs):
        kwargs["on_edit"](1)

    monkeypatch.setattr(
        tasks_render.task_operation_cards, "render_operation_cards", render_cards
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "render_active_dialog",
        lambda state, **kwargs: calls.append(("dialog", state)),
    )

    tasks_render._render_form_editor()

    state = fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE]
    assert state.mode == "edit"
    assert state.source_index == 1
    assert state.working_copy == operations[1]
    assert calls == [("dialog", state)]


def test_form_editor_blocker_opens_prefilled_suggestion_dialog(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    blocker = {
        "kind": "migration-blocker",
        "params": {
            "intent": "Add a MARC field",
            "reason": "External option needs confirmation.",
            "suggestion": {
                "operation_kind": "add-field",
                "prefilled_params": {
                    "tag": "877",
                    "subfields": [["m", "Image"]],
                },
            },
            "instruction_sha256": "a" * 64,
        },
    }
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = [blocker]
    calls = []
    _wire_compact_form(monkeypatch, tasks_render, calls)

    def render_cards(_ops, **kwargs):
        kwargs["on_suggestion"](0)

    monkeypatch.setattr(
        tasks_render.task_operation_cards,
        "render_operation_cards",
        render_cards,
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "render_active_dialog",
        lambda state, **kwargs: calls.append(("dialog", state)),
    )

    tasks_render._render_form_editor()

    state = fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE]
    assert state.source_index == 0
    assert state.working_copy["kind"] == "add-field"
    assert state.opening_value == blocker
    assert calls == [("dialog", state)]


def test_active_operation_dialog_suppresses_stale_reference_request(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    state = tasks_render.task_operation_dialog.new_add_state(4)
    fake_st.session_state.update({
        tasks_render.K_EDITOR_OPS: [],
        tasks_render.K_OPERATION_DIALOG_STATE: state,
        tasks_render.K_OPERATION_REFERENCE_REQUESTED: True,
    })
    calls = []
    _wire_compact_form(monkeypatch, tasks_render, calls)
    monkeypatch.setattr(
        tasks_render.task_operation_cards,
        "render_operation_cards",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "render_active_dialog",
        lambda active, **kwargs: calls.append(("dialog", active)),
    )

    tasks_render._render_form_editor()

    assert calls == [("dialog", state)]
    assert not fake_st.session_state[
        tasks_render.K_OPERATION_REFERENCE_REQUESTED
    ]


def test_dialog_capability_error_fails_loud_without_opening_wrapper(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update({
        tasks_render.K_EDITOR_OPS: [],
        tasks_render.K_OPERATION_DIALOG_STATE:
            tasks_render.task_operation_dialog.new_add_state(1),
        tasks_render.K_OPERATION_REFERENCE_REQUESTED: True,
    })
    calls = []
    _wire_compact_form(monkeypatch, tasks_render, calls)
    monkeypatch.setattr(
        tasks_render.task_operation_cards,
        "render_operation_cards",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "dialog_contract_error",
        lambda: "non-dismissible dialogs unavailable",
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "render_active_dialog",
        lambda *args, **kwargs: calls.append(("dialog", {})),
    )

    tasks_render._render_form_editor()

    assert fake_st.errors == ["non-dismissible dialogs unavailable"]
    assert calls == []
    assert not fake_st.session_state[
        tasks_render.K_OPERATION_REFERENCE_REQUESTED
    ]


def test_reference_button_opens_only_reference_dialog(monkeypatch):
    fake_st = _FakeStreamlit()
    fake_st.clicked_labels.add("Browse operation reference")
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = []
    calls = []
    _wire_compact_form(monkeypatch, tasks_render, calls)
    monkeypatch.setattr(
        tasks_render.task_operation_cards,
        "render_operation_cards",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "render_active_dialog",
        lambda *args, **kwargs: calls.append(("dialog", {})),
    )

    tasks_render._render_form_editor()

    assert len(calls) == 1
    assert calls[0][0] == "reference"
    assert calls[0][1]["include_custom"] is False
    calls[0][1]["on_close"]()
    assert not fake_st.session_state[
        tasks_render.K_OPERATION_REFERENCE_REQUESTED
    ]


def _wire_successful_save(monkeypatch, tasks_render, saved):
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render, "_ai_draft_save_blocked_for_new_task", lambda: False
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )
    monkeypatch.setattr(
        tasks_render.task_db, "materialize_to_dir", lambda *args: None
    )
    monkeypatch.setattr(
        tasks_render.tasks, "load_user_tasks", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        tasks_render.task_admin, "is_admin", lambda user: False
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *args, **kwargs: None)


def _form_save_state(tasks_render, operations):
    return {
        tasks_render.K_EDITOR_NAME_INPUT: "structured-fields",
        tasks_render.K_EDITOR_DESCRIPTION_INPUT: "",
        tasks_render.K_EDITOR_MODE: "form",
        tasks_render.K_EDITOR_VISIBILITY: "private",
        tasks_render.K_EDITOR_OPS: operations,
    }


def _migration_blocker():
    return {
        "kind": "migration-blocker",
        "params": {
            "intent": "Edit control field 001",
            "reason": "Exact external mode is unproven",
            "suggestion": {
                "operation_kind": "set-control-field",
                "prefilled_params": {"tag": "001"},
            },
            "instruction_sha256": "a" * 64,
        },
    }


def test_form_save_persists_blocker_and_labels_migration_review(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(tasks_render, [_migration_blocker()])
    )
    pending = {"status": "partial", "entries": []}
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = pending
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert len(saved) == 1
    assert "# OP: migration-blocker" in saved[0]["body"]
    assert fake_st.session_state[tasks_render.K_SAVE_SUCCESS] == (
        "Saved `structured-fields`. Needs migration review."
    )
    assert fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] == pending


def test_queued_submission_rejects_marker_before_constructing_task_spec(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    rendered = tasks_render.task_builder.render_ops_to_python([
        tasks_render.Operation.from_dict(_migration_blocker())
    ])
    monkeypatch.setattr(
        tasks_render.editor,
        "parse_user_task_file",
        lambda _path: {
            "name": "blocked",
            "description": "",
            "body": rendered["body"],
        },
    )
    submitted = []
    monkeypatch.setattr(
        tasks_render.operation_submission,
        "submit_quick_load_task_run",
        lambda **kwargs: submitted.append(kwargs),
    )
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)

    tasks_render._submit_queued_run(["blocked"], tmp_path)

    assert submitted == []
    assert any("Resolve 1 imported instruction" in error for error in fake_st.errors)


def test_queued_submission_rejects_malformed_marker_before_task_spec(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    monkeypatch.setattr(
        tasks_render.editor,
        "parse_user_task_file",
        lambda _path: {
            "name": "malformed",
            "description": "",
            "body": "# OP: delete-tag {not-json}\npass",
        },
    )
    submitted = []
    monkeypatch.setattr(
        tasks_render.operation_submission,
        "submit_quick_load_task_run",
        lambda **kwargs: submitted.append(kwargs),
    )

    tasks_render._submit_queued_run(["malformed"], tmp_path)

    assert submitted == []
    assert any("Malformed operation marker" in error for error in fake_st.errors)


def test_incomplete_kept_card_blocks_task_save_with_ordinal(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [{"kind": "delete-tag", "params": {"tag": ""}}],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "Operation 1: Tag is required" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_editor_open_and_close_reset_operation_dialog_lifecycle(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    stale = tasks_render.task_operation_dialog.new_add_state(9)
    fake_st.session_state.update({
        tasks_render.K_OPERATION_DIALOG_STATE: stale,
        tasks_render.K_OPERATION_DIALOG_NONCE: 9,
        tasks_render.K_OPERATION_REFERENCE_REQUESTED: True,
    })

    tasks_render._open_editor_for_new()

    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE] is None
    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_NONCE] == 0
    assert not fake_st.session_state[
        tasks_render.K_OPERATION_REFERENCE_REQUESTED
    ]

    fake_st.session_state.update({
        tasks_render.K_EDITOR_FROM_AI_DRAFT: True,
        tasks_render.K_OPERATION_DIALOG_STATE: stale,
        tasks_render.K_OPERATION_DIALOG_NONCE: 9,
        tasks_render.K_OPERATION_REFERENCE_REQUESTED: True,
    })
    tasks_render._clear_ai_draft_review()

    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE] is None
    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_NONCE] == 0
    assert not fake_st.session_state[
        tasks_render.K_OPERATION_REFERENCE_REQUESTED
    ]

    fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE] = stale
    fake_st.session_state[tasks_render.K_OPERATION_REFERENCE_REQUESTED] = True
    tasks_render._cancel_callback()

    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE] is None
    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_NONCE] == 0
    assert not fake_st.session_state[
        tasks_render.K_OPERATION_REFERENCE_REQUESTED
    ]


def test_pending_remove_confirmation_does_not_cross_task_lifecycles(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[
        tasks_render.K_OPERATION_CARDS_PENDING_REMOVE
    ] = 0

    tasks_render._cancel_callback()

    assert (
        tasks_render.K_OPERATION_CARDS_PENDING_REMOVE
        not in fake_st.session_state
    )

    fake_st.session_state[
        tasks_render.K_OPERATION_CARDS_PENDING_REMOVE
    ] = 0
    tasks_render._open_editor_for_new()

    assert (
        tasks_render.K_OPERATION_CARDS_PENDING_REMOVE
        not in fake_st.session_state
    )


def test_form_save_reports_non_object_params_by_ordinal_without_persisting(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operation = {"kind": "delete-tag", "params": ["opaque"]}
    original = copy.deepcopy(operation)
    fake_st.session_state.update(
        _form_save_state(tasks_render, [operation])
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert fake_st.session_state[tasks_render.K_SAVE_ERROR] == (
        "Operation 1: operation parameters must be an object"
    )
    assert operation == original


def test_clear_my_tasks_resets_operation_dialog_lifecycle_before_rerun(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    fake_st.clicked_labels.add("Clear my tasks")
    tasks_render = _tasks_render(monkeypatch, fake_st)
    stale = tasks_render.task_operation_dialog.new_add_state(9)
    fake_st.session_state.update({
        tasks_render.K_EDITOR_OPEN: True,
        tasks_render.K_OPERATION_DIALOG_STATE: stale,
        tasks_render.K_OPERATION_DIALOG_NONCE: 9,
        tasks_render.K_OPERATION_REFERENCE_REQUESTED: True,
    })
    monkeypatch.setattr(
        fake_st, "metric", lambda *args, **kwargs: None, raising=False
    )
    monkeypatch.setattr(
        fake_st,
        "rerun",
        lambda: (_ for _ in ()).throw(RuntimeError("rerun")),
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "count_visible",
        lambda user: {"own": 1, "shared_from_others": 0},
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "list_own_tasks",
        lambda user: [{"name": "cleanup"}],
    )
    monkeypatch.setattr(
        tasks_render.task_db, "delete_task", lambda user, name: None
    )

    with pytest.raises(RuntimeError, match="rerun"):
        tasks_render._render_build_mode(
            Path("/unused"),
            is_admin=False,
            current_user_id="cat@smith.edu",
            registered=[],
        )

    assert not fake_st.session_state[tasks_render.K_EDITOR_OPEN]
    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_STATE] is None
    assert fake_st.session_state[tasks_render.K_OPERATION_DIALOG_NONCE] == 0
    assert not fake_st.session_state[
        tasks_render.K_OPERATION_REFERENCE_REQUESTED
    ]


def test_valid_raw_regex_saves_without_file_or_preview(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operation = {
        "kind": "guided-find-replace",
        "params": {
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "raw_regex",
            "find": r"^(TFeba)(\d+)$",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": r"(SCTFEBA)\2",
            "occurrences": "all",
            "condition": "always",
        },
    }
    fake_st.session_state.update(
        _form_save_state(tasks_render, [operation])
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: None)

    tasks_render._save_callback(tmp_path)

    assert tasks_render.K_SAVE_ERROR not in fake_st.session_state
    assert len(saved) == 1


def test_save_blocks_invalid_structured_field_before_sql(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [
                {
                    "kind": "add-field",
                    "params": {
                        "tag": "877",
                        "ind1": " ",
                        "ind2": " ",
                        "subfields": [],
                        "existing_field_action": "append",
                        "condition": "always",
                    },
                }
            ],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "Operation 1" in fake_st.session_state[tasks_render.K_SAVE_ERROR]
    assert "at least one subfield" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_unconvertible_legacy_build_remains_visible_but_blocks_form_save(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [
                {
                    "kind": "build-field",
                    "authoring_error": (
                        "cannot convert legacy Build Field text losslessly"
                    ),
                    "params": {
                        "tag": "876",
                        "ind1": " ",
                        "ind2": " ",
                        "subfields": [["a", "literal {name}"]],
                    },
                }
            ],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "cannot convert" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_existing_unresolved_custom_op_can_be_preserved_during_save(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [
                {
                    "kind": "custom",
                    "params": {
                        "code": (
                            "# TODO: buildnewfield template "
                            "'=876  \\\\$a{001}' — recreate with "
                            "structured Build Field"
                        )
                    },
                }
            ],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert len(saved) == 1


def test_synthetic_mixed_task_blocks_unresolved_then_round_trips_after_removal(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operations = [
        {
            "kind": "add-field",
            "params": {
                "tag": "650",
                "ind1": " ",
                "ind2": "0",
                "subfields": [["a", "Synthetic topic"]],
                "condition": "always",
                "existing_field_action": "append",
            },
        },
        {
            "kind": "build-field",
            "params": {
                "tag": "035",
                "ind1": " ",
                "ind2": " ",
                "structured_subfields": [[
                    "a",
                    [
                        {"type": "text", "value": "("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                    ],
                ]],
                "condition": "always",
                "existing_field_action": "append",
                "missing_control_action": "skip_field",
            },
        },
        {
            "kind": "guided-find-replace",
            "params": {
                "target_kind": "subfield",
                "tag": "245",
                "subfield": "a",
                "match_mode": "contains",
                "find": "Synthetic old",
                "ignore_case": False,
                "replacement_mode": "matched_text",
                "replacement": "Synthetic new",
                "occurrences": "all",
                "value_scope": "all",
                "condition": "always",
            },
        },
        {"kind": "delete-tag", "params": {"tag": "999"}},
        {
            "kind": "custom",
            "params": {
                "code": "record.leader = record.leader  # synthetic"
            },
        },
        {
            "kind": "future-operation",
            "params": {"opaque": ["keep", {"nested": True}]},
            "authoring_error": "synthetic operation needs review",
        },
    ]
    expected_operations = copy.deepcopy(operations)
    expected_operations[3]["params"]["tag"] = "949"
    expected_operations[3], expected_operations[4] = (
        expected_operations[4],
        expected_operations[3],
    )
    source_operations = copy.deepcopy(operations)
    edit_state = tasks_render.task_operation_dialog.new_edit_state(
        source_operations[3], index=3, nonce=1
    )
    edit_state.working_copy["params"]["tag"] = "949"
    operations = tasks_render.task_operation_dialog.keep_in_task(
        source_operations, edit_state
    )
    operations = tasks_render.task_operation_cards.move_operation(
        operations, 4, -1
    )
    assert source_operations[3]["params"]["tag"] == "999"
    assert operations == expected_operations
    fake_st.session_state.update(_form_save_state(tasks_render, operations))
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert fake_st.session_state[tasks_render.K_SAVE_ERROR] == (
        "Operation 6: synthetic operation needs review"
    )

    valid_operations = tasks_render.task_operation_cards.remove_operation(
        operations, 5
    )
    expected_valid_operations = expected_operations[:5]
    assert valid_operations == expected_valid_operations
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = valid_operations
    fake_st.session_state.pop(tasks_render.K_SAVE_ERROR)

    tasks_render._save_callback(tmp_path)

    assert len(saved) == 1
    parsed = tasks_render.task_builder.parse_ops_from_source(saved[0]["body"])
    assert parsed["form_editable"] is True
    assert parsed["reason"] is None
    assert [
        operation.to_dict() for operation in parsed["ops"]
    ] == expected_valid_operations


def test_valid_guided_raw_regex_saves_without_a_loaded_file(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [
                {
                    "kind": "guided-find-replace",
                    "params": {
                        "target_kind": "subfield",
                        "tag": "035",
                        "subfield": "a",
                        "match_mode": "raw_regex",
                        "find": r"^(TFeba)(\d+)$",
                        "ignore_case": False,
                        "replacement_mode": "matched_text",
                        "replacement": r"(SCTFEBA)\2",
                        "occurrences": "all",
                        "condition": "always",
                    },
                }
            ],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(
        tasks_render.session, "current_store", lambda: None
    )

    tasks_render._save_callback(tmp_path)

    assert len(saved) == 1
    assert tasks_render.K_SAVE_ERROR not in fake_st.session_state


def test_invalid_guided_raw_capture_blocks_save_without_loaded_file(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operation = {
        "kind": "guided-find-replace",
        "params": {
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "raw_regex",
            "find": r"(TFeba)",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": r"\2",
            "occurrences": "all",
            "condition": "always",
        },
    }
    fake_st.session_state.update(
        _form_save_state(tasks_render, [operation])
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: None)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "invalid group reference" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_guided_raw_validation_timeout_blocks_save_without_crashing(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operation = {
        "kind": "guided-find-replace",
        "params": {
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "raw_regex",
            "find": "TFeba",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": "replacement",
            "occurrences": "all",
            "condition": "always",
        },
    }
    fake_st.session_state.update(
        _form_save_state(tasks_render, [operation])
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(
        tasks_render.task_authoring.guided_replace_validation,
        "validate_raw_regex",
        lambda **_kwargs: (
            "Regular expression validation timed out in the sandbox.",
        ),
    )

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "timed out" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_guided_raw_preexec_failure_blocks_save_without_crashing(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operation = {
        "kind": "guided-find-replace",
        "params": {
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "raw_regex",
            "find": "TFeba",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": "replacement",
            "occurrences": "all",
            "condition": "always",
        },
    }
    fake_st.session_state.update(
        _form_save_state(tasks_render, [operation])
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(
        tasks_render.task_authoring.guided_replace_validation.sandbox,
        "run_tasks_subprocess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.SubprocessError("preexec failed")
        ),
    )

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "preexec failed" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_oversized_guided_raw_save_fails_before_syntax_launch(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operation = {
        "kind": "guided-find-replace",
        "params": {
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "raw_regex",
            "find": "TFeba",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": "x" * 3000,
            "occurrences": "all",
            "condition": "always",
        },
    }
    fake_st.session_state.update(
        _form_save_state(tasks_render, [operation])
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(
        tasks_render.task_authoring.guided_replace_validation,
        "validate_raw_regex",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("oversized request must not launch validation")
        ),
    )

    tasks_render._save_callback(tmp_path)

    assert saved == []
    error = fake_st.session_state[tasks_render.K_SAVE_ERROR]
    assert "request" in error.lower()
    assert "limit" in error.lower()


def test_stale_form_errors_do_not_block_code_mode_save(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        {
            tasks_render.K_EDITOR_NAME_INPUT: "code-task",
            tasks_render.K_EDITOR_DESCRIPTION_INPUT: "",
            tasks_render.K_EDITOR_MODE: "code",
            tasks_render.K_EDITOR_VISIBILITY: "private",
            tasks_render.K_EDITOR_BODY: "pass",
            tasks_render.K_EDITOR_OPS: [
                {
                    "kind": "add-field",
                    "params": {"tag": "bad", "subfields": []},
                }
            ],
        }
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert len(saved) == 1


def test_new_unresolved_text_import_is_not_persisted(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.quotas, "check_upload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *args, **kwargs: None)
    saved = []
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )
    upload = SimpleNamespace(
        name="rda.tasksfile",
        getvalue=lambda: b"RDAHELPER\n",
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    result = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert result["status"] == "partial"
    assert result["rejection_category"] == "unresolved-instructions"
    assert result["imported_task_names"] == []
    assert len(result["entries"]) == 1
    assert result["entries"][0]["status"] == "needs_review"
    assert result["entries"][0]["task_name"] == "rda"
    assert result["entries"][0]["draft"]["summary"]["blocking"] == 1


def test_empty_find_101_import_opens_add_if_missing_draft(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.quotas, "check_upload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        tasks_render, "audit_event", lambda *args, **kwargs: None
    )
    saved = []
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )
    upload = SimpleNamespace(
        name="empty-find.tasksfile",
        getvalue=lambda: (
            b"SUBFIELD_EDIT\t856\ty\t\t"
            b"Smith: Link to resource\t101|0\n"
        ),
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    assert fake_st.session_state[tasks_render.K_EDITOR_OPS] == [{
        "kind": "empty-find-subfield-policy",
        "params": {
            "tag": "856",
            "code": "y",
            "value": "Smith: Link to resource",
            "policy": "add_if_missing",
        },
    }]
    assert tasks_render.K_MARCEDIT_IMPORT_RESULT not in fake_st.session_state


def test_import_result_persists_across_rerun_and_is_dismissible(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    big = [f"line-{index}" for index in range(1, 25)]
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = {
        "status": "rejected",
        "uploaded_filename": "bulk.txt",
        "imported_task_names": [],
        "entries": [{
            "entry_name": "bulk.txt",
            "status": "unresolved",
            "task_name": "bulk-task",
            "message": "this task contains unresolved external instructions",
            "unresolved_lines": big,
            "omitted_unresolved": 4,
        }],
        "rejection_category": "unresolved-instructions",
    }

    tasks_render._render_marcedit_import_result()

    assert fake_st.warnings  # status summary rendered as warning
    assert fake_st.code_blocks == big[:20]
    assert fake_st.captions[-1] == "4 additional unresolved lines omitted."
    assert fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] is not None

    fake_st.clicked_labels.add("Dismiss")
    tasks_render._render_marcedit_import_result()
    assert tasks_render.K_MARCEDIT_IMPORT_RESULT not in fake_st.session_state


def test_malformed_import_result_is_discarded_without_crashing(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = {
        "status": "rejected",
        "uploaded_filename": "broken.task",
        "entries": 42,
    }

    tasks_render._render_marcedit_import_result()

    assert tasks_render.K_MARCEDIT_IMPORT_RESULT not in fake_st.session_state
    assert fake_st.errors == [
        "Stored import result is invalid. Re-import the source file."
    ]


def _retained_partial_draft_payload(tasks_render):
    conversion = tasks_render.marcedit_import.convert_tasksfile_text(
        (
            "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
            "UNKNOWN\texternal intent\n"
            "SORTBY\tALL\tTrue\tTrue\n"
        ),
        name="mixed",
        description_fallback="",
        source_entry="mixed.tasksfile",
    )
    return {
        "status": "partial",
        "uploaded_filename": "mixed.tasksfile",
        "imported_task_names": [],
        "entries": [{
            "entry_name": "mixed.tasksfile",
            "status": "needs_review",
            "task_name": "mixed",
            "message": "editable draft contains instructions needing review",
            "draft": conversion.draft.to_session_dict(),
        }],
        "rejection_category": "unresolved-instructions",
    }


@pytest.mark.parametrize(
    "corruption",
    [
        "converted_count",
        "blocking_count",
        "total_count",
        "ready_with_blocker",
        "task_identity",
        "source_entry_identity",
        "source_line_digest",
        "blocker_digest",
        "operation_digest",
        "provenance_order",
    ],
)
def test_retained_draft_cross_checks_counts_identity_and_provenance(
    monkeypatch, corruption
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    payload = _retained_partial_draft_payload(tasks_render)
    entry = payload["entries"][0]
    draft = entry["draft"]

    if corruption == "converted_count":
        draft["summary"]["converted"] += 1
    elif corruption == "blocking_count":
        draft["summary"]["blocking"] = 0
    elif corruption == "total_count":
        draft["summary"]["total"] += 1
    elif corruption == "ready_with_blocker":
        entry["status"] = "draft_ready"
    elif corruption == "task_identity":
        draft["task_name"] = "different"
    elif corruption == "source_entry_identity":
        draft["provenance"][1]["source_entry"] = "other.tasksfile"
    elif corruption == "source_line_digest":
        draft["provenance"][1]["source_line"] = "changed"
    elif corruption == "blocker_digest":
        draft["operations"][1]["params"]["instruction_sha256"] = "0" * 64
    elif corruption == "operation_digest":
        draft["provenance"][1]["operation_digests"][0] = "0" * 64
    elif corruption == "provenance_order":
        draft["provenance"][0], draft["provenance"][2] = (
            draft["provenance"][2], draft["provenance"][0]
        )

    normalized = tasks_render._normalize_marcedit_import_result(payload)

    assert normalized["entries"][0]["status"] == "failed"
    assert normalized["entries"][0]["draft"] is None
    assert normalized["entries"][0]["message"] == (
        "Stored migration draft is invalid. Re-import the source file."
    )

    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = payload
    tasks_render._render_marcedit_import_result()
    assert any("Stored migration draft is invalid" in error for error in fake_st.errors)
    assert "Open migration draft" not in fake_st.button_labels
    assert "Open selected draft" not in fake_st.button_labels


@pytest.mark.parametrize(
    ("constant_name", "corruption"),
    [
        ("MAX_DRAFT_PROVENANCE_ITEMS", "provenance"),
        ("MAX_DRAFT_SOURCE_ENTRY_BYTES", "source_entry"),
        ("MAX_DRAFT_SOURCE_LINE_BYTES", "source_line"),
        ("MAX_DRAFT_DISCLOSURES", "disclosures"),
        ("MAX_DRAFT_OPERATIONS", "operations"),
    ],
)
def test_retained_draft_enforces_concrete_payload_bounds(
    monkeypatch, constant_name, corruption
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    payload = _retained_partial_draft_payload(tasks_render)
    draft = payload["entries"][0]["draft"]
    monkeypatch.setattr(tasks_render, constant_name, 1)
    if corruption == "provenance":
        pass
    elif corruption == "source_entry":
        draft["provenance"][0]["source_entry"] = "xx"
    elif corruption == "source_line":
        draft["provenance"][0]["source_line"] = "xx"
    elif corruption == "disclosures":
        draft["disclosures"] = ["one", "two"]
    elif corruption == "operations":
        draft["operations"].append(draft["operations"][0].copy())

    normalized = tasks_render._normalize_marcedit_import_result(payload)

    assert normalized["entries"][0]["status"] == "failed"
    assert normalized["entries"][0]["draft"] is None


def test_unresolved_import_result_keeps_actionable_warning_copy(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = {
        "status": "rejected",
        "uploaded_filename": "legacy.tasksfile",
        "imported_task_names": [],
        "entries": [{
            "entry_name": "legacy.tasksfile",
            "status": "unresolved",
            "message": "this task contains unresolved external instructions",
            "unresolved_lines": ["RDAHELPER"],
            "omitted_unresolved": 0,
        }],
        "rejection_category": "unresolved-instructions",
    }

    tasks_render._render_marcedit_import_result()

    assert fake_st.warnings[0].startswith(
        "Some instructions need your confirmation"
    )
    assert any(
        "Open the editable draft" in warning
        for warning in fake_st.warnings
    )


def test_dismiss_import_result_requests_immediate_rerun(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = {
        "status": "success",
        "uploaded_filename": "ok.tasksfile",
        "imported_task_names": ["ok"],
        "entries": [],
    }
    fake_st.clicked_labels.add("Dismiss")

    tasks_render._render_marcedit_import_result()

    assert tasks_render.K_MARCEDIT_IMPORT_RESULT not in fake_st.session_state
    assert fake_st.rerun_called


def test_upload_read_exception_is_durable_and_replaces_old_result(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = {
        "status": "success",
        "uploaded_filename": "old.tasksfile",
        "imported_task_names": ["old"],
        "entries": [],
    }

    def fail_read():
        raise OSError("upload read failed")

    upload = SimpleNamespace(name="new.tasksfile", getvalue=fail_read)
    tasks_render._do_marcedit_import(upload, tmp_path)

    result = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert result["status"] == "rejected"
    assert result["rejection_category"] == "unexpected"
    assert "upload read failed" in result["entries"][0]["message"]


def test_archive_parsing_never_writes_tasks(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.quotas, "check_upload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *args, **kwargs: None)
    ok = tasks_render.marcedit_import.convert_tasksfile_text(
        "SORTBY\tALL\tTrue\tTrue\n", name="ok", description_fallback=""
    )
    later = tasks_render.marcedit_import.convert_tasksfile_text(
        "SORTBY\tALL\tTrue\tTrue\n", name="later", description_fallback=""
    )
    archive = SimpleNamespace(
        archive_errors=[],
        entries=[
            SimpleNamespace(
                entry_name="ok.txt", success=True, conversion=ok,
                draft=ok.draft, error=None,
            ),
            SimpleNamespace(
                entry_name="later.txt", success=True, conversion=later,
                draft=later.draft, error=None,
            ),
        ],
    )
    monkeypatch.setattr(tasks_render, "_convert_uploaded_archive", lambda *args: archive)
    saved = []

    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("parsing must not write tasks")
        ),
    )
    upload = SimpleNamespace(name="bundle.task", getvalue=lambda: b"archive")

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    result = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert result["status"] == "success"
    assert [entry["status"] for entry in result["entries"]] == [
        "draft_ready", "draft_ready"
    ]


def _wire_import_test(monkeypatch, tasks_render, saved):
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.quotas, "check_upload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )


def test_successful_text_import_opens_editor_without_durable_result(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    upload = SimpleNamespace(
        name="delete-029.tasksfile",
        getvalue=lambda: (
            b"DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
        ),
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "delete-029"
    assert tasks_render.K_MARCEDIT_IMPORT_RESULT not in fake_st.session_state


def test_fully_converted_text_import_opens_draft_without_database_write(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    upload = SimpleNamespace(
        name="delete-029.tasksfile",
        getvalue=lambda: (
            b"DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
            b"SORTBY\tALL\tTrue\tTrue\n"
        ),
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    assert fake_st.session_state[tasks_render.K_EDITOR_OPEN] is True
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "delete-029"
    assert [
        operation["kind"]
        for operation in fake_st.session_state[tasks_render.K_EDITOR_OPS]
    ] == ["delete-tag", "sort-fields"]
    assert fake_st.session_state[
        tasks_render.K_EDITOR_IMPORT_SUMMARY
    ] == {"converted": 2, "blocking": 0, "total": 2}


def test_partial_text_import_waits_for_adoption_then_opens_ordered_blockers(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    upload = SimpleNamespace(
        name="mixed.tasksfile",
        getvalue=lambda: (
            b"DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
            b"UNKNOWN\texternal intent\n"
            b"SORTBY\tALL\tTrue\tTrue\n"
        ),
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    stored = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert stored["entries"][0]["status"] == "needs_review"
    assert stored["entries"][0]["draft"]["summary"] == {
        "converted": 2,
        "blocking": 1,
        "total": 3,
    }
    tasks_render._render_marcedit_import_result()
    assert fake_st.warnings[0].startswith(
        "Some instructions need your confirmation"
    )

    fake_st.session_state["unrelated_state"] = "preserved"
    fake_st.clicked_labels.add("Open migration draft")
    tasks_render._render_marcedit_import_result()

    assert [
        operation["kind"]
        for operation in fake_st.session_state[tasks_render.K_EDITOR_OPS]
    ] == ["delete-tag", "migration-blocker", "sort-fields"]
    assert fake_st.session_state["unrelated_state"] == "preserved"


def test_multi_entry_archive_presents_chooser_without_writing_tasks(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    valid = tasks_render.marcedit_import.convert_tasksfile_text(
        "DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n",
        name="valid",
        description_fallback="",
        source_entry="same.txt",
    )
    blocked = tasks_render.marcedit_import.convert_tasksfile_text(
        "UNKNOWN\texternal intent\n",
        name="blocked",
        description_fallback="",
        source_entry="same.txt",
    )
    archive = SimpleNamespace(
        archive_errors=[],
        entries=[
            SimpleNamespace(
                entry_name="same.txt",
                success=True,
                conversion=valid,
                draft=valid.draft,
                error=None,
            ),
            SimpleNamespace(
                entry_name="same.txt",
                success=True,
                conversion=blocked,
                draft=blocked.draft,
                error=None,
            ),
        ],
    )
    monkeypatch.setattr(
        tasks_render, "_convert_uploaded_archive", lambda *args: archive
    )
    upload = SimpleNamespace(name="bundle.task", getvalue=lambda: b"archive")

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    stored = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert stored["status"] == "partial"
    assert [entry["status"] for entry in stored["entries"]] == [
        "draft_ready",
        "needs_review",
    ]
    tasks_render._render_marcedit_import_result()
    assert "Open selected draft" in fake_st.button_labels
    assert tasks_render.K_MARCEDIT_IMPORT_RESULT in fake_st.session_state

    fake_st.clicked_labels.add("Open selected draft")
    tasks_render._render_marcedit_import_result()
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "valid"
    assert tasks_render.K_MARCEDIT_IMPORT_RESULT in fake_st.session_state
    assert fake_st.session_state[
        tasks_render.K_MARCEDIT_IMPORT_ADOPTED_ENTRY
    ] == "0"

    fake_st.clicked_labels = {"Open migration draft"}
    tasks_render._render_marcedit_import_result()
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "blocked"


def test_single_fully_converted_archive_opens_directly_without_task_write(
    monkeypatch, tmp_path
):
    import io
    import zipfile

    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("solo.txt", "SORTBY\tALL\tTrue\tTrue\n")
    upload = SimpleNamespace(
        name="bundle.task", getvalue=payload.getvalue
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "solo"
    assert fake_st.session_state[tasks_render.K_EDITOR_OPS] == [{
        "kind": "sort-fields",
        "params": {},
    }]


def test_archive_import_preserves_mixed_entry_outcomes(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    ok = tasks_render.marcedit_import.convert_tasksfile_text(
        "SORTBY\tALL\tTrue\tTrue\n", name="ok", description_fallback=""
    )
    unresolved = tasks_render.marcedit_import.convert_tasksfile_text(
        "UNKNOWN\texternal intent\n",
        name="needs-review",
        description_fallback="",
    )
    archive = SimpleNamespace(
        archive_errors=[],
        entries=[
            SimpleNamespace(
                entry_name="ok.txt",
                success=True,
                conversion=ok,
                draft=ok.draft,
                error=None,
            ),
            SimpleNamespace(
                entry_name="needs-review.txt",
                success=True,
                conversion=unresolved,
                draft=unresolved.draft,
                error=None,
            ),
        ],
    )
    monkeypatch.setattr(
        tasks_render, "_convert_uploaded_archive", lambda *args: archive
    )
    upload = SimpleNamespace(
        name="bundle.task", getvalue=lambda: b"archive-bytes"
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    result = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert result["status"] == "partial"
    assert [entry["status"] for entry in result["entries"]] == [
        "draft_ready", "needs_review"
    ]
    assert result["entries"][1]["draft"]["summary"]["blocking"] == 1


def test_quota_rejection_is_durable_and_categorized(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(
        tasks_render.quotas,
        "check_upload",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            tasks_render.quotas.QuotaExceeded("tasksfile", 10, 5)
        ),
    )
    upload = SimpleNamespace(name="too-large.tasksfile", getvalue=lambda: b"x")

    tasks_render._do_marcedit_import(upload, tmp_path)

    result = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert saved == []
    assert result["status"] == "rejected"
    assert result["rejection_category"] == "quota"


def test_unexpected_import_exception_is_durable(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(
        tasks_render.marcedit_import,
        "convert_tasksfile_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("converter failed")
        ),
    )
    upload = SimpleNamespace(name="broken.tasksfile", getvalue=lambda: b"x")

    tasks_render._do_marcedit_import(upload, tmp_path)

    result = fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT]
    assert result["status"] == "rejected"
    assert result["rejection_category"] == "unexpected"
    assert "converter failed" in result["entries"][0]["message"]


def test_later_import_replaces_previous_result(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    saved = []
    _wire_import_test(monkeypatch, tasks_render, saved)
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = {
        "status": "rejected",
        "uploaded_filename": "old.tasksfile",
        "imported_task_names": [],
        "entries": [{"status": "failed", "message": "old"}],
    }
    upload = SimpleNamespace(
        name="new.tasksfile",
        getvalue=lambda: (
            b"DELETE\t029\t\t0\tFalse\tFalse\tFalse\tFalse\tFalse\n"
        ),
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert tasks_render.K_MARCEDIT_IMPORT_RESULT not in fake_st.session_state
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "new"


def test_save_callback_reports_invalid_form_regex_without_persisting(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update({
        tasks_render.K_EDITOR_NAME_INPUT: "invalid-regex",
        tasks_render.K_EDITOR_DESCRIPTION_INPUT: "Invalid regex task",
        tasks_render.K_EDITOR_MODE: "form",
        tasks_render.K_EDITOR_VISIBILITY: "private",
        tasks_render.K_EDITOR_OPS: [{
            "kind": "replace-field-subfield-and-indicators",
            "params": {
                "tag": "035",
                "match_ind1": " ",
                "match_ind2": " ",
                "match_code": "a",
                "match_value": "(",
                "regex": True,
                "ignore_case": False,
                "new_ind1": " ",
                "new_ind2": "9",
                "new_code": "a",
                "new_value": "replacement",
            },
        }],
    })
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render, "_ai_draft_save_blocked_for_new_task", lambda: False
    )
    saved = []
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "invalid match regex" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]
