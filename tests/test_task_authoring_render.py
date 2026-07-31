"""Focused widget-contract tests for structured task authoring."""

from __future__ import annotations

import pytest
from pymarc import Field, Record

from marcedit_web.lib.guided_replace_preview import GuidedReplacePreview


class RerunRequested(Exception):
    pass


class GuardedSessionState(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instantiated_widget_keys = set()

    def begin_run(self):
        self.instantiated_widget_keys.clear()

    def mark_widget(self, key):
        if key is not None:
            self.instantiated_widget_keys.add(key)

    def __setitem__(self, key, value):
        if key in self.instantiated_widget_keys:
            raise AssertionError(
                "cannot write an instantiated widget key: {0}".format(key)
            )
        super().__setitem__(key, value)


class FakeStreamlit:
    def __init__(
        self,
        pressed=None,
        *,
        checked=None,
        selectbox_values=None,
        session_state=None,
        text_values=None,
        guard_widget_state=False,
        raise_on_rerun=False,
    ):
        self.pressed = set(pressed or ())
        self.checked = None if checked is None else set(checked)
        self.selectbox_values = dict(selectbox_values or {})
        self.text_values = dict(text_values or {})
        self.raise_on_rerun = raise_on_rerun
        if guard_widget_state and not isinstance(
            session_state, GuardedSessionState
        ):
            session_state = GuardedSessionState(session_state or {})
        self.session_state = session_state if session_state is not None else {}
        if isinstance(self.session_state, GuardedSessionState):
            self.session_state.begin_run()
        self.text_input_labels = []
        self.text_area_labels = []
        self.selectbox_labels = []
        self.checkbox_labels = []
        self.radio_labels = []
        self.widget_keys = []
        self.button_keys = []
        self.captions = []
        self.code_blocks = []
        self.markdown_blocks = []
        self.warnings = []
        self.errors = []
        self.infos = []
        self.rerun_count = 0

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]

    def text_input(self, label, value="", **kwargs):
        self.text_input_labels.append(label)
        key = kwargs.get("key")
        self.widget_keys.append(key)
        if isinstance(self.session_state, GuardedSessionState):
            self.session_state.mark_widget(key)
        return self.text_values.get(label, value)

    def text_area(self, label, value="", **kwargs):
        self.text_area_labels.append(label)
        return value

    def selectbox(
        self, label, options, index=0, format_func=None, **kwargs
    ):
        self.selectbox_labels.append(label)
        key = kwargs.get("key")
        self.widget_keys.append(key)
        selected = self.selectbox_values.get(
            label,
            self.session_state.get(key, options[index]),
        )
        dict.__setitem__(self.session_state, key, selected)
        if isinstance(self.session_state, GuardedSessionState):
            self.session_state.mark_widget(key)
        return selected

    def checkbox(self, label, value=False, key=None, **kwargs):
        self.checkbox_labels.append(label)
        self.widget_keys.append(key)
        if self.checked is not None:
            selected = key in self.checked
        else:
            selected = self.session_state.get(key, False)
        dict.__setitem__(self.session_state, key, selected)
        if isinstance(self.session_state, GuardedSessionState):
            self.session_state.mark_widget(key)
        return selected

    def radio(self, label, options, index=0, key=None, **kwargs):
        self.radio_labels.append(label)
        self.widget_keys.append(key)
        if isinstance(self.session_state, GuardedSessionState):
            self.session_state.mark_widget(key)
        return options[index]

    def metric(self, label, value, **kwargs):
        return None

    def spinner(self, text):
        return self

    def button(self, label, key=None, **kwargs):
        self.button_keys.append(key)
        self.widget_keys.append(key)
        if isinstance(self.session_state, GuardedSessionState):
            self.session_state.mark_widget(key)
        return key in self.pressed

    def caption(self, value):
        self.captions.append(value)

    def code(self, value, **kwargs):
        self.code_blocks.append(value)

    def markdown(self, value):
        self.markdown_blocks.append(value)

    def warning(self, value):
        self.warnings.append(value)

    def error(self, value):
        self.errors.append(value)

    def info(self, value):
        self.infos.append(value)

    def expander(self, label):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def rerun(self):
        self.rerun_count += 1
        if self.raise_on_rerun:
            raise RerunRequested


def _renderer(monkeypatch, fake):
    from marcedit_web.render import task_authoring as renderer

    monkeypatch.setattr(renderer, "st", fake)
    return renderer


def _source_record():
    record = Record()
    record.add_field(Field(tag="001", data="SYNTHETIC12345"))
    record.add_field(Field(tag="003", data="NhCcYBP"))
    return record


def _smith_035_operation():
    return {
        "kind": "build-field",
        "params": {
            "tag": "035",
            "ind1": "9",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {"type": "text", "value": "("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                    ],
                ]
            ],
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
            "condition": "always",
        },
    }


def _smith_876_operation():
    return {
        "kind": "build-field",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [
                [
                    "a",
                    [
                        {"type": "text", "value": "B("},
                        {"type": "control_field", "tag": "003"},
                        {"type": "text", "value": ")"},
                        {"type": "control_field", "tag": "001"},
                        {"type": "text", "value": "-SC"},
                    ],
                ],
                ["l", [{"type": "text", "value": "Internet"}]],
            ],
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
            "condition": "always",
        },
    }


def _guided_operation(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "contains",
        "find": "TFeba",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "(SCTFEBA)",
        "occurrences": "all",
        "condition": "always",
    }
    params.update(changes)
    return {"kind": "guided-find-replace", "params": params}


def test_guided_default_shows_plain_find_without_regex(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert "Where should Smith Metadata Studio look?" in fake.selectbox_labels
    assert "Find" in fake.text_input_labels
    assert "Write a regular expression directly" in fake.checkbox_labels
    assert params["match_mode"] == "contains"


def test_explicit_target_switch_clears_now_hidden_subfield(monkeypatch):
    fake = FakeStreamlit(
        selectbox_values={
            "Where should Smith Metadata Studio look?": "control_field"
        }
    )
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert params["target_kind"] == "control_field"
    assert params["subfield"] == ""


def test_loaded_inconsistent_hidden_subfield_remains_fail_loud(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation(
        target_kind="control_field",
        tag="001",
    )["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert params["subfield"] == "a"
    assert renderer.task_authoring.validate_operation(
        {"kind": "guided-find-replace", "params": params}
    ) == ("Subfield code must be empty for this target.",)


@pytest.mark.parametrize("replacement_mode", ["prepend", "append"])
def test_prepend_append_hide_find_regex_and_occurrence_controls(
    monkeypatch, replacement_mode
):
    fake = FakeStreamlit(
        selectbox_values={"What should it change?": replacement_mode}
    )
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert "Find" not in fake.text_input_labels
    assert (
        "Write a regular expression directly" not in fake.checkbox_labels
    )
    assert "First or every match?" not in fake.radio_labels
    assert params["match_mode"] == "none"
    assert params["find"] == ""
    assert params["occurrences"] == "all"


def test_raw_regex_is_explicit_and_preserves_entered_strings(monkeypatch):
    fake = FakeStreamlit(
        checked={"op_0_advanced_regex"},
        text_values={
            "Find regular expression": r"^(TFeba)(\d+)$",
            "Replace with": r"(SCTFEBA)\2",
        },
    )
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert params["match_mode"] == "raw_regex"
    assert params["find"] == r"^(TFeba)(\d+)$"
    assert params["replacement"] == r"(SCTFEBA)\2"


def test_leaving_raw_mode_requires_confirmation_before_discard(monkeypatch):
    params = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
    )["params"]
    shared_state = GuardedSessionState()
    first = FakeStreamlit(
        pressed={"op_0_mode_switch_discard"},
        session_state=shared_state,
        guard_widget_state=True,
        raise_on_rerun=True,
    )
    renderer = _renderer(monkeypatch, first)
    with pytest.raises(RerunRequested):
        renderer.render_guided_find_replace_params(
            params, key_prefix="op_0"
        )
    assert first.rerun_count == 1
    assert params["match_mode"] == "raw_regex"
    assert params["find"] == r"^(TFeba)(\d+)$"
    assert any("discard" in text.lower() for text in first.warnings)

    confirmed = FakeStreamlit(
        session_state=shared_state,
        guard_widget_state=True,
    )
    renderer = _renderer(monkeypatch, confirmed)
    renderer.render_guided_find_replace_params(
        params, key_prefix="op_0"
    )
    assert params["match_mode"] == "contains"
    assert params["find"] == ""
    assert confirmed.warnings == []


@pytest.mark.parametrize(
    ("previous_action", "requested_action"),
    [("matched_text", "prepend"), ("whole_value", "append")],
)
def test_keep_raw_mode_cancels_prepend_append_without_widget_state_write(
    monkeypatch, previous_action, requested_action
):
    params = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
        replacement_mode=previous_action,
        occurrences="first" if previous_action == "whole_value" else "all",
    )["params"]
    shared_state = GuardedSessionState()
    first = FakeStreamlit(
        pressed={"op_0_mode_switch_keep"},
        checked={"op_0_advanced_regex"},
        selectbox_values={"What should it change?": requested_action},
        session_state=shared_state,
        guard_widget_state=True,
        raise_on_rerun=True,
    )
    renderer = _renderer(monkeypatch, first)

    with pytest.raises(RerunRequested):
        renderer.render_guided_find_replace_params(
            params, key_prefix="op_0"
        )
    assert first.rerun_count == 1

    rerun = FakeStreamlit(
        session_state=shared_state,
        guard_widget_state=True,
    )
    renderer = _renderer(monkeypatch, rerun)
    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert rerun.warnings == []
    assert params["replacement_mode"] == previous_action
    assert params["match_mode"] == "raw_regex"
    assert params["find"] == r"^(TFeba)(\d+)$"
    assert params["replacement"] == r"(SCTFEBA)\2"


@pytest.mark.parametrize("requested_action", ["prepend", "append"])
def test_discard_raw_mode_canonicalizes_prepend_append_without_stale_state(
    monkeypatch, requested_action
):
    params = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
    )["params"]
    shared_state = GuardedSessionState()
    first = FakeStreamlit(
        pressed={"op_0_mode_switch_discard"},
        checked={"op_0_advanced_regex"},
        selectbox_values={"What should it change?": requested_action},
        session_state=shared_state,
        guard_widget_state=True,
        raise_on_rerun=True,
    )
    renderer = _renderer(monkeypatch, first)

    with pytest.raises(RerunRequested):
        renderer.render_guided_find_replace_params(
            params, key_prefix="op_0"
        )
    assert first.rerun_count == 1

    rerun = FakeStreamlit(
        session_state=shared_state,
        guard_widget_state=True,
    )
    renderer = _renderer(monkeypatch, rerun)
    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert params["replacement_mode"] == requested_action
    assert params["match_mode"] == "none"
    assert params["find"] == ""
    assert params["occurrences"] == "all"
    assert params["replacement"] == r"(SCTFEBA)\2"
    assert (
        "Write a regular expression directly" not in rerun.checkbox_labels
    )
    assert "op_0_preserved_raw_find" not in shared_state


def test_guided_widget_keys_are_unique_and_operation_scoped(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)

    renderer.render_guided_find_replace_params(
        _guided_operation()["params"], key_prefix="op_0"
    )

    keys = [key for key in fake.widget_keys if key is not None]
    assert len(keys) == len(set(keys))
    assert all(key.startswith("op_0_") for key in keys)


def test_guided_preview_runs_only_on_button_and_replaces_request_cache(
    monkeypatch,
):
    operation = _guided_operation()
    fake = FakeStreamlit(pressed={"op_0_preview"})
    renderer = _renderer(monkeypatch, fake)
    preview = GuidedReplacePreview(
        request=operation,
        store_id=7,
        store_revision=0,
        before="035 $aTFeba123",
        after="035 $a(SCTFEBA)123",
        result={
            "matched_values": 1,
            "changed_values": 1,
            "matched_occurrences": 1,
        },
    )
    calls = []
    monkeypatch.setattr(
        renderer.guided_replace_preview,
        "build_preview",
        lambda store, op: calls.append((store, op)) or preview,
    )
    cache = {}

    renderer.render_guided_replace_preview(
        operation, object(), cache, key_prefix="op_0"
    )

    assert len(calls) == 1
    assert list(cache.values()) == [preview]
    assert any("Matched values: 1" in text for text in fake.captions)
    assert fake.code_blocks[-2:] == [
        "035 $aTFeba123",
        "035 $a(SCTFEBA)123",
    ]


def test_guided_preview_does_not_rerun_sandbox_and_reports_zero_matches(
    monkeypatch,
):
    operation = _guided_operation()
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    preview = GuidedReplacePreview(
        request=operation,
        store_id=7,
        store_revision=0,
        result={
            "matched_values": 0,
            "changed_values": 0,
            "matched_occurrences": 0,
        },
    )
    key = renderer.guided_replace_preview.preview_cache_key(operation)
    cache = {key: preview}
    monkeypatch.setattr(
        renderer.guided_replace_preview,
        "build_preview",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("preview runs only when its button is pressed")
        ),
    )

    renderer.render_guided_replace_preview(
        operation, object(), cache, key_prefix="op_0"
    )

    assert any("zero matches" in text.lower() for text in fake.infos)


def test_condition_skipped_preview_names_condition_without_zero_match(
    monkeypatch,
):
    operation = _guided_operation(condition="serials")
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    preview = GuidedReplacePreview(
        request=operation["params"],
        store_id=7,
        store_revision=0,
        before="035 $aTFeba123",
        after="035 $aTFeba123",
        result={
            "matched_values": 0,
            "changed_values": 0,
            "matched_occurrences": 0,
        },
        condition_skipped=True,
    )
    key = renderer.guided_replace_preview.preview_cache_key(operation)
    cache = {key: preview}

    renderer.render_guided_replace_preview(
        operation, object(), cache, key_prefix="op_0"
    )

    assert any(
        "skipped" in text.lower() and "serial" in text.lower()
        for text in fake.infos
    )
    assert not any("zero matches" in text.lower() for text in fake.infos)


def test_oversized_guided_preview_request_is_not_cached(monkeypatch):
    operation = _guided_operation(
        replacement="x" * 3000,
    )
    fake = FakeStreamlit(pressed={"op_0_preview"})
    renderer = _renderer(monkeypatch, fake)
    cache = {}

    renderer.render_guided_replace_preview(
        operation, object(), cache, key_prefix="op_0"
    )

    assert cache == {}
    assert any(
        "request" in message.lower() and "limit" in message.lower()
        for message in fake.errors
    )


def test_only_current_successful_whole_value_preview_supplies_discard_count(
    monkeypatch,
):
    operation = _guided_operation(
        replacement_mode="whole_value",
        occurrences="first",
    )

    class Store:
        revision = 4

    store = Store()
    renderer = _renderer(monkeypatch, FakeStreamlit())
    key = renderer.guided_replace_preview.preview_cache_key(operation)
    current = GuidedReplacePreview(
        request=operation["params"],
        store_id=id(store),
        store_revision=4,
        result={"matched_values": 3},
    )

    assert renderer.guided_replace_previewed_discard_count(
        operation, store, {key: current}
    ) == 3
    assert renderer.guided_replace_previewed_discard_count(
        operation,
        store,
        {
            key: GuidedReplacePreview(
                request=operation["params"],
                store_id=id(store),
                store_revision=3,
                result={"matched_values": 9},
            )
        },
    ) == 0
    assert renderer.guided_replace_previewed_discard_count(
        operation,
        store,
        {
            key: GuidedReplacePreview(
                request=operation["params"],
                store_id=id(store),
                store_revision=4,
                result={"matched_values": 9},
                error="preview failed",
            )
        },
    ) == 0
    assert renderer.guided_replace_previewed_discard_count(
        operation, store, {}
    ) == 0


def test_guided_technical_details_show_saved_choices_pattern_and_docs_link(
    monkeypatch,
):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)

    renderer.render_guided_replace_technical_details(_guided_operation())

    technical = "\n".join(fake.code_blocks)
    assert "target_kind=subfield" in technical
    assert "match_mode=contains" in technical
    assert "Generated match pattern: TFeba" in technical
    assert any(
        (
            "https://github.com/sclibraries/marcedit-web/blob/main/"
            "docs/task-authoring-syntax.md"
        )
        in block
        for block in fake.markdown_blocks
    )


def test_add_field_uses_rows_instead_of_json_textarea(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    params = {
        "tag": "877",
        "ind1": " ",
        "ind2": " ",
        "subfields": [["m", "Map"]],
        "existing_field_action": "append",
        "condition": "always",
    }
    renderer.render_add_field_params(params, key_prefix="op_0")
    assert "Subfield code" in fake.text_input_labels
    assert "Subfield value" in fake.text_input_labels
    assert fake.text_area_labels == []


def test_add_subfield_button_appends_one_blank_row(monkeypatch):
    fake = FakeStreamlit(pressed={"op_0_add_subfield"})
    renderer = _renderer(monkeypatch, fake)
    params = {
        "tag": "877",
        "ind1": " ",
        "ind2": " ",
        "subfields": [["a", "first"]],
        "existing_field_action": "append",
        "condition": "always",
    }
    renderer.render_add_field_params(params, key_prefix="op_0")
    assert params["subfields"] == [["a", "first"], ["", ""]]
    assert fake.rerun_count == 1


def test_build_field_renders_typed_text_and_control_segments(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    params = _smith_876_operation()["params"]
    renderer.render_build_field_params(params, key_prefix="op_0")
    assert "Segment type" in fake.selectbox_labels
    assert "Literal text" in fake.text_input_labels
    assert "Source control field" in fake.text_input_labels


def test_operation_panel_shows_plain_mnemonic_annotations_and_preview(
    monkeypatch,
):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    renderer.render_operation_explanation(
        _smith_035_operation(), _source_record()
    )
    assert any("Add an 035 field" in text for text in fake.captions)
    assert any("=035" in text for text in fake.code_blocks)
    assert any(
        "control field 003" in text for text in fake.markdown_blocks
    )


def test_unconvertible_legacy_build_renders_raw_value_instead_of_crashing(
    monkeypatch,
):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    operation = {
        "kind": "build-field",
        "authoring_error": "cannot convert legacy Build Field text losslessly",
        "params": {
            "tag": "876",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["a", "literal {name}"]],
        },
    }
    renderer.render_operation_explanation(operation, _source_record())
    assert any("cannot convert" in warning for warning in fake.warnings)
    assert any("literal {name}" in block for block in fake.code_blocks)


def test_non_mapping_params_render_raw_value_instead_of_crashing(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    operation = {
        "kind": "add-field",
        "authoring_error": "operation parameters must be an object",
        "params": ["future", "shape"],
    }
    renderer.render_operation_explanation(operation, _source_record())
    assert fake.warnings == ["operation parameters must be an object"]
    assert any("future" in block for block in fake.code_blocks)


def test_nested_subfield_and_segment_button_keys_are_unique(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    renderer.render_build_field_params(
        _smith_876_operation()["params"],
        key_prefix="op_0",
    )
    assert len(fake.button_keys) == len(set(fake.button_keys))
    assert any(key.startswith("op_0_sf_0_") for key in fake.button_keys)
    assert any(
        key.startswith("op_0_sf_0_seg_0_")
        for key in fake.button_keys
    )
