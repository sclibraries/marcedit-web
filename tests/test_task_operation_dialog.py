from __future__ import annotations

import copy

import pytest
from streamlit.errors import StreamlitAPIException
from streamlit.runtime.scriptrunner_utils.exceptions import StopException

from marcedit_web.lib import (
    guided_replace_preview,
    task_authoring,
    task_builder,
)
from marcedit_web.render import task_operation_cards, task_operation_dialog


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeStreamlit:
    def __init__(self, *, selections=None, pressed=()):
        self.selections = selections or {}
        self.pressed = set(pressed)
        self.dialog_calls = []
        self.wrapper_invocations = 0
        self.tab_calls = []
        self.column_calls = []
        self.widgets = []
        self.raw_values = []
        self.errors = []
        self.reruns = []
        self.session_state = {}

    def dialog(self, title, *, width, dismissible):
        self.dialog_calls.append({
            "title": title,
            "width": width,
            "dismissible": dismissible,
        })

        def decorate(function):
            def wrapped():
                self.wrapper_invocations += 1
                function()

            return wrapped

        return decorate

    def tabs(self, labels):
        self.tab_calls.append(list(labels))
        return [_Context() for _label in labels]

    def selectbox(self, label, *, options, key, index=0, **kwargs):
        self.widgets.append(("selectbox", label, list(options), key))
        default = None if index is None else options[index]
        return self.selections.get(label, default)

    def button(self, label, *, key, **kwargs):
        self.widgets.append(("button", label, None, key))
        return label in self.pressed

    def json(self, value):
        self.raw_values.append(value)

    def error(self, value):
        self.errors.append(value)

    def caption(self, value):
        return None

    def markdown(self, value):
        return None

    def warning(self, value):
        return None

    def code(self, value, **kwargs):
        self.raw_values.append(value)

    def columns(self, spec):
        self.column_calls.append(spec)
        count = spec if isinstance(spec, int) else len(spec)
        return [_Context() for _index in range(count)]

    def rerun(self, **kwargs):
        self.reruns.append(kwargs)


def test_edit_isolated_until_keep_and_cancel_preserves_original():
    original = {
        "kind": "delete-tag",
        "params": {"tag": "001"},
    }
    operations = [original]
    state = task_operation_dialog.new_edit_state(
        original, index=0, nonce=7
    )
    state.working_copy["params"]["tag"] = "003"

    assert operations == [original]
    assert task_operation_dialog.cancel_result(state) == "confirm"
    assert task_operation_dialog.keep_in_task(operations, state) == [{
        "kind": "delete-tag",
        "params": {"tag": "003"},
    }]
    assert operations == [original]


def test_clean_cancel_closes_without_confirmation():
    operation = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(
        operation, index=0, nonce=1
    )

    assert task_operation_dialog.cancel_result(state) == "close"


def test_edit_opening_and_working_values_are_independent_deep_copies():
    operation = {"kind": "custom", "params": {"nested": [["original"]]}}
    state = task_operation_dialog.new_edit_state(
        operation, index=0, nonce=2
    )

    operation["params"]["nested"][0][0] = "source changed"
    state.working_copy["params"]["nested"][0][0] = "draft changed"

    assert state.opening_value["params"]["nested"] == [["original"]]


def test_keep_rejects_missing_add_selection_and_stale_edit_index():
    with pytest.raises(ValueError, match="select an operation"):
        task_operation_dialog.keep_in_task(
            [], task_operation_dialog.new_add_state(3)
        )

    operation = {"kind": "delete-tag", "params": {"tag": "001"}}
    stale = task_operation_dialog.new_edit_state(
        operation, index=1, nonce=4
    )
    with pytest.raises(ValueError, match="no longer in the task"):
        task_operation_dialog.keep_in_task([operation], stale)


def test_add_kind_uses_existing_defaults_and_incomplete_draft_can_be_kept():
    state = task_operation_dialog.select_add_kind(
        task_operation_dialog.new_add_state(3),
        "guided-find-replace",
    )

    kept = task_operation_dialog.keep_in_task([], state)

    assert kept[0]["kind"] == "guided-find-replace"
    assert kept[0]["params"]["replacement_mode"] == "matched_text"
    assert task_authoring.validate_operation(kept[0])


def _add_subfield_position_parameter():
    entry = task_operation_dialog._palette_entry("add-subfield")
    return next(
        parameter
        for parameter in entry["params"]
        if parameter["name"] == "position"
    )


def test_generic_select_render_preserves_unsupported_value(monkeypatch):
    fake = FakeStreamlit()
    params = {"position": "future"}
    monkeypatch.setattr(task_operation_dialog, "st", fake)

    task_operation_dialog.render_param_input(
        _add_subfield_position_parameter(),
        params,
        key_prefix="operation_1",
    )

    assert params["position"] == "future"


def test_generic_select_render_can_repair_unsupported_value(monkeypatch):
    fake = FakeStreamlit(selections={"Position": "start"})
    params = {"position": "future"}
    monkeypatch.setattr(task_operation_dialog, "st", fake)

    task_operation_dialog.render_param_input(
        _add_subfield_position_parameter(),
        params,
        key_prefix="operation_1",
    )

    assert params["position"] == "start"


@pytest.mark.parametrize(
    "kind",
    [entry["kind"] for entry in task_builder.OPERATIONS_PALETTE],
)
def test_every_palette_kind_enters_the_shared_admin_dialog(kind, monkeypatch):
    fake = FakeStreamlit(selections={"Operation": kind})
    state = task_operation_dialog.new_add_state(1)
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[],
        is_admin=True,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert sorted(fake.widgets[0][2]) == sorted(
        entry["kind"]
        for entry in task_builder.OPERATIONS_PALETTE
    )
    assert state.selected_kind == kind
    assert state.working_copy["kind"] == kind
    assert isinstance(state.working_copy["params"], dict)
    assert fake.reruns == [{}]


def test_dialog_contract_checks_capability_not_version_string():
    def supported(title, *, width="small", dismissible=True):
        return title, width, dismissible

    def unsupported(title, *, width="small"):
        return title, width

    assert task_operation_dialog.dialog_contract_error(supported) is None
    assert "dismissible" in task_operation_dialog.dialog_contract_error(
        unsupported
    )


def test_dialog_contract_resolves_current_streamlit_dialog(monkeypatch):
    def supported(title, *, width="small", dismissible=True):
        return title, width, dismissible

    monkeypatch.setattr(task_operation_dialog.st, "dialog", supported)

    assert task_operation_dialog.dialog_contract_error() is None


def test_fragment_rerun_falls_back_to_app_scope(monkeypatch):
    calls = []

    def rerun(*, scope="app"):
        calls.append(scope)
        if scope == "fragment":
            raise StreamlitAPIException("not in fragment context")

    monkeypatch.setattr(task_operation_dialog.st, "rerun", rerun)

    task_operation_dialog.rerun_fragment_or_app()

    assert calls == ["fragment", "app"]


def test_fragment_rerun_does_not_fall_back_after_success(monkeypatch):
    calls = []

    def rerun(*, scope="app"):
        calls.append(scope)

    monkeypatch.setattr(task_operation_dialog.st, "rerun", rerun)

    task_operation_dialog.rerun_fragment_or_app()

    assert calls == ["fragment"]


def test_fragment_rerun_does_not_swallow_unexpected_errors(monkeypatch):
    def rerun(*, scope="app"):
        raise RuntimeError(scope)

    monkeypatch.setattr(task_operation_dialog.st, "rerun", rerun)

    with pytest.raises(RuntimeError, match="fragment"):
        task_operation_dialog.rerun_fragment_or_app()


def test_guided_edit_uses_one_large_nondismissible_split_workspace(
    monkeypatch,
):
    fake = FakeStreamlit()
    state = task_operation_dialog.select_add_kind(
        task_operation_dialog.new_add_state(8),
        "guided-find-replace",
    )
    state.mode = "edit"
    state.source_index = 0
    state.opening_value = state.working_copy.copy()
    controls = []
    previews = []
    references = []
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "render_guided_find_replace_params",
        lambda params, **kwargs: controls.append(kwargs),
    )
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "render_guided_replace_preview",
        lambda *args, **kwargs: previews.append(kwargs) or 0,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "render_guided_replace_technical_details",
        lambda operation: None,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: references.append(entry["kind"]),
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[state.opening_value],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert fake.dialog_calls == [{
        "title": "Edit — Guided find and replace",
        "width": "large",
        "dismissible": False,
    }]
    assert fake.tab_calls == [[
        "Workspace", "Technical details", "Reference"
    ]]
    assert fake.column_calls == [[5, 6]]
    assert fake.wrapper_invocations == 1
    assert controls[0]["rerun"] is task_operation_dialog.rerun_fragment_or_app
    assert previews
    assert references == ["guided-find-replace"]


def test_delete_tag_has_only_workspace_and_reference_tabs(monkeypatch):
    fake = FakeStreamlit()
    operation = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(operation, index=0, nonce=4)
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog,
        "render_param_input",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[operation],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert fake.tab_calls == [["Workspace", "Reference"]]
    assert fake.column_calls == []


def test_structural_retag_workspace_exposes_action_and_match_text(monkeypatch):
    operation = {
        "kind": "structural-find-replace",
        "params": {
            "target_kind": "field_tag",
            "tag": "035",
            "match_mode": "contains",
            "find": "TFeba",
            "action": "retag",
            "destination_tag": "936",
        },
    }
    state = task_operation_dialog.new_edit_state(operation, index=0, nonce=40)
    rendered = []
    monkeypatch.setattr(
        task_operation_dialog,
        "render_param_input",
        lambda parameter, *args, **kwargs: rendered.append(parameter["name"]),
    )

    task_operation_dialog.render_selected_operation(state, is_admin=False)

    assert "action" in rendered
    assert "find" in rendered


def test_add_starts_with_alphabetical_selector_and_no_controls(monkeypatch):
    fake = FakeStreamlit()
    controls = []
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog,
        "render_selected_operation",
        lambda *args, **kwargs: controls.append(args),
    )

    task_operation_dialog.render_active_dialog(
        task_operation_dialog.new_add_state(9),
        operations=[],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    widget_type, label, options, key = fake.widgets[0]
    labels = [task_operation_dialog._palette_entry(kind)["label"] for kind in options]
    assert (widget_type, label) == ("selectbox", "Operation")
    assert labels == sorted(labels, key=str.casefold)
    assert "custom" not in options
    assert key.startswith("task_operation_dialog_9_")
    assert controls == []
    assert fake.column_calls == []


def test_non_admin_add_excludes_only_custom_and_cancel_preserves_custom_code(
    monkeypatch,
):
    fake = FakeStreamlit()
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        task_operation_dialog.new_add_state(10),
        operations=[],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    selectable_kinds = fake.widgets[0][2]
    assert set(selectable_kinds) == {
        entry["kind"]
        for entry in task_builder.OPERATIONS_PALETTE
        if entry["kind"] != "custom"
    }

    code = "record.leader = record.leader  # synthetic"
    custom = {"kind": "custom", "params": {"code": code}}
    state = task_operation_dialog.new_edit_state(custom, index=0, nonce=11)
    fake = FakeStreamlit(pressed={"Cancel"})
    kept = []
    closed = []
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[custom],
        is_admin=False,
        store=None,
        previews={},
        on_keep=kept.append,
        on_close=lambda: closed.append(True),
    )

    assert code in fake.raw_values
    assert kept == []
    assert closed == [True]
    assert state.working_copy == custom
    assert custom["params"]["code"] == code


def test_add_selection_rebuilds_wrapper_with_selected_operation_title(
    monkeypatch,
):
    fake = FakeStreamlit(selections={"Operation": "delete-tag"})
    state = task_operation_dialog.new_add_state(10)
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert state.working_copy == {
        "kind": "delete-tag",
        "params": {"tag": ""},
    }
    assert fake.dialog_calls[0]["title"] == "Add operation"
    assert fake.reruns == [{}]

    fake.dialog_calls.clear()
    fake.reruns.clear()
    monkeypatch.setattr(
        task_operation_dialog,
        "render_selected_operation",
        lambda state, *, is_admin: None,
    )
    task_operation_dialog.render_active_dialog(
        state,
        operations=[],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert fake.dialog_calls[0]["title"] == "Add — Delete tag"


def test_unknown_draft_is_preserved_and_renderer_failure_is_bounded(monkeypatch):
    fake = FakeStreamlit()
    unknown = {
        "kind": "retired-operation",
        "params": {"opaque": ["keep", {"this": "value"}]},
        "authoring_error": "This imported operation needs migration.",
    }
    state = task_operation_dialog.new_edit_state(unknown, index=0, nonce=12)
    monkeypatch.setattr(task_operation_dialog, "st", fake)

    task_operation_dialog.render_active_dialog(
        state,
        operations=[unknown],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert fake.tab_calls == [["Workspace", "Technical details", "Reference"]]
    assert unknown in fake.raw_values
    assert any("needs migration" in error for error in fake.errors)
    assert state.working_copy == unknown

    guided = task_operation_dialog.select_add_kind(
        task_operation_dialog.new_add_state(13),
        "guided-find-replace",
    )
    preserved = guided.working_copy.copy()
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "render_guided_find_replace_params",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("broken")),
    )
    task_operation_dialog.render_active_dialog(
        guided,
        operations=[],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )
    assert any("could not be displayed: broken" in error for error in fake.errors)
    assert guided.working_copy == preserved


def test_bounded_renderer_failure_restores_pre_render_draft(monkeypatch):
    fake = FakeStreamlit()
    original = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(original, index=0, nonce=13)
    monkeypatch.setattr(task_operation_dialog, "st", fake)

    def mutate_then_fail(state, *, is_admin):
        state.working_copy["params"]["tag"] = "partial mutation"
        state.working_copy["params"]["nested"] = [{"changed": True}]
        raise ValueError("broken after mutation")

    monkeypatch.setattr(
        task_operation_dialog,
        "render_selected_operation",
        mutate_then_fail,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[original],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert state.working_copy == original
    assert state.working_copy is not original
    assert any("broken after mutation" in error for error in fake.errors)


def test_streamlit_control_flow_is_not_swallowed_or_rolled_back(monkeypatch):
    fake = FakeStreamlit()
    original = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(original, index=0, nonce=14)
    kept = []
    closed = []
    monkeypatch.setattr(task_operation_dialog, "st", fake)

    def mutate_then_stop(state, *, is_admin):
        state.working_copy["params"]["tag"] = "intentional mutation"
        raise StopException()

    monkeypatch.setattr(
        task_operation_dialog,
        "render_selected_operation",
        mutate_then_stop,
    )

    with pytest.raises(StopException):
        task_operation_dialog.render_active_dialog(
            state,
            operations=[original],
            is_admin=False,
            store=None,
            previews={},
            on_keep=kept.append,
            on_close=lambda: closed.append(True),
        )

    assert state.working_copy["params"]["tag"] == "intentional mutation"
    assert fake.errors == []
    assert kept == []
    assert closed == []


@pytest.mark.parametrize(
    ("kind", "renderer_name", "exception"),
    [
        ("add-field", "render_add_field_params", OSError("add failed")),
        (
            "build-field",
            "render_build_field_params",
            RuntimeError("build failed"),
        ),
        (
            "guided-find-replace",
            "render_guided_find_replace_params",
            TypeError("guided setup failed"),
        ),
        (
            "guided-find-replace",
            "render_guided_replace_preview",
            ValueError("guided preview failed"),
        ),
        (
            "add-field",
            "render_operation_explanation",
            OSError("field preview failed"),
        ),
        (
            "guided-find-replace",
            "render_guided_replace_technical_details",
            RuntimeError("technical details failed"),
        ),
    ],
)
def test_each_delegated_renderer_failure_is_bounded_and_transactional(
    monkeypatch,
    kind,
    renderer_name,
    exception,
):
    fake = FakeStreamlit()
    state = task_operation_dialog.select_add_kind(
        task_operation_dialog.new_add_state(40), kind
    )
    if kind == "guided-find-replace":
        state.working_copy["params"].update({
            "tag": "245",
            "subfield": "a",
            "find": "old",
            "replacement": "new",
        })
    state.working_copy["params"]["rollback_probe"] = {
        "nested": {"value": "original"}
    }
    before_render = copy.deepcopy(state.working_copy)
    kept = []
    closed = []
    delegated_renderers = (
        "render_add_field_params",
        "render_build_field_params",
        "render_guided_find_replace_params",
        "render_guided_replace_preview",
        "render_operation_explanation",
        "render_guided_replace_technical_details",
    )
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    for delegated_name in delegated_renderers:
        monkeypatch.setattr(
            task_operation_dialog.task_authoring_render,
            delegated_name,
            lambda *args, **kwargs: None,
        )
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "guided_replace_previewed_discard_count",
        lambda *args, **kwargs: 0,
    )

    def raise_bounded_exception(*args, **kwargs):
        probe = state.working_copy["params"]["rollback_probe"]
        probe["nested"]["value"] = "mutated"
        probe["nested"]["added"] = ["must", "roll", "back"]
        raise exception

    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        renderer_name,
        raise_bounded_exception,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[],
        is_admin=True,
        store=None,
        previews={},
        on_keep=kept.append,
        on_close=lambda: closed.append(True),
    )

    assert fake.errors == [
        "This operation could not be displayed: {0}".format(exception)
    ]
    assert state.working_copy == before_render
    assert state.working_copy["params"]["rollback_probe"] == {
        "nested": {"value": "original"}
    }
    assert kept == []
    assert closed == []


def test_malformed_guided_technical_renderer_failure_is_bounded(monkeypatch):
    fake = FakeStreamlit()
    malformed = {"kind": "guided-find-replace", "params": {}}
    state = task_operation_dialog.new_edit_state(
        malformed, index=0, nonce=14
    )
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "render_guided_find_replace_params",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "render_guided_replace_preview",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "guided_replace_previewed_discard_count",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        task_operation_dialog.task_authoring_render,
        "render_guided_replace_technical_details",
        lambda operation: (_ for _ in ()).throw(ValueError("malformed")),
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[malformed],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert any("could not be displayed: malformed" in error for error in fake.errors)
    assert state.working_copy == malformed


def test_keep_commits_copy_and_requests_app_rerun(monkeypatch):
    fake = FakeStreamlit(pressed={"Keep in task"})
    original = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(original, index=0, nonce=21)
    state.working_copy["params"]["tag"] = "003"
    kept = []
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog, "render_param_input", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[original],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: kept.extend(operations),
        on_close=lambda: None,
    )

    assert kept == [{"kind": "delete-tag", "params": {"tag": "003"}}]
    assert fake.reruns == [{}]
    assert original["params"]["tag"] == "001"


def test_dirty_cancel_requires_explicit_discard(monkeypatch):
    fake = FakeStreamlit(pressed={"Cancel"})
    original = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(original, index=0, nonce=22)
    state.working_copy["params"]["tag"] = "003"
    closed = []
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog, "render_param_input", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[original],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: closed.append(True),
    )

    assert state.discard_pending is True
    assert closed == []
    assert fake.reruns == []
    assert "Discard changes" in [widget[1] for widget in fake.widgets]
    assert "Keep editing" in [widget[1] for widget in fake.widgets]


def test_confirmed_discard_closes_and_clean_cancel_closes(monkeypatch):
    original = {"kind": "delete-tag", "params": {"tag": "001"}}
    for pressed, dirty in (("Discard changes", True), ("Cancel", False)):
        fake = FakeStreamlit(pressed={pressed})
        state = task_operation_dialog.new_edit_state(original, index=0, nonce=23)
        if dirty:
            state.working_copy["params"]["tag"] = "003"
            state.discard_pending = True
        closed = []
        monkeypatch.setattr(task_operation_dialog, "st", fake)
        monkeypatch.setattr(
            task_operation_dialog,
            "render_param_input",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            task_operation_dialog.task_operation_reference,
            "render_reference_entry",
            lambda entry: None,
        )

        task_operation_dialog.render_active_dialog(
            state,
            operations=[original],
            is_admin=False,
            store=None,
            previews={},
            on_keep=lambda operations: None,
            on_close=lambda: closed.append(True),
        )

        assert closed == [True]
        assert fake.reruns == [{}]


def test_keep_editing_clears_discard_state_and_reruns_fragment(monkeypatch):
    fake = FakeStreamlit(pressed={"Keep editing"})
    operation = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(operation, index=0, nonce=25)
    state.working_copy["params"]["tag"] = "003"
    state.discard_pending = True
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog, "render_param_input", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[operation],
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    assert state.discard_pending is False
    assert fake.reruns == [{"scope": "fragment"}]


def test_all_dialog_widget_keys_use_nonce_not_source_index(monkeypatch):
    fake = FakeStreamlit()
    operation = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(operation, index=47, nonce=24)
    monkeypatch.setattr(task_operation_dialog, "st", fake)
    monkeypatch.setattr(
        task_operation_dialog, "render_param_input", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        task_operation_dialog.task_operation_reference,
        "render_reference_entry",
        lambda entry: None,
    )

    task_operation_dialog.render_active_dialog(
        state,
        operations=[operation] * 48,
        is_admin=False,
        store=None,
        previews={},
        on_keep=lambda operations: None,
        on_close=lambda: None,
    )

    keys = [widget[3] for widget in fake.widgets]
    assert keys
    assert all(key.startswith("task_operation_dialog_24_") for key in keys)
    assert all("47" not in key for key in keys)


class _PreviewStore:
    revision = 5


def _guided_operation(replacement):
    state = task_operation_dialog.select_add_kind(
        task_operation_dialog.new_add_state(30),
        "guided-find-replace",
    )
    operation = state.working_copy
    operation["params"].update({
        "tag": "245",
        "subfield": "a",
        "find": "old",
        "replacement": replacement,
    })
    return operation


def test_cancelled_draft_preview_cannot_impersonate_original_request():
    store = _PreviewStore()
    original = _guided_operation("original")
    operations = [original]
    original_request = task_authoring.normalize_operation(original)["params"]
    previews = {
        guided_replace_preview.preview_cache_key(original):
        guided_replace_preview.GuidedReplacePreview(
            request=original_request,
            store_id=id(store),
            store_revision=store.revision,
        )
    }
    state = task_operation_dialog.new_edit_state(original, index=0, nonce=31)
    state.working_copy["params"]["replacement"] = "discarded draft"
    draft = state.working_copy
    draft_request = task_authoring.normalize_operation(draft)["params"]
    previews[guided_replace_preview.preview_cache_key(draft)] = (
        guided_replace_preview.GuidedReplacePreview(
            request=draft_request,
            store_id=id(store),
            store_revision=store.revision,
        )
    )

    assert task_operation_dialog.cancel_result(state) == "confirm"

    restored = operations[0]
    view = task_operation_cards.operation_card_view(
        restored,
        position=1,
        store=store,
        previews=previews,
    )
    assert view.preview_status == "Current"
    assert guided_replace_preview.preview_cache_key(draft) in previews
    assert guided_replace_preview.preview_cache_key(restored) != (
        guided_replace_preview.preview_cache_key(draft)
    )
