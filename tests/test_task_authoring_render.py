"""Focused widget-contract tests for structured task authoring."""

from __future__ import annotations

from pymarc import Field, Record


class FakeStreamlit:
    def __init__(
        self,
        pressed=None,
        *,
        checked=None,
        selectbox_values=None,
        text_values=None,
    ):
        self.pressed = set(pressed or ())
        self.checked = set(checked or ())
        self.selectbox_values = dict(selectbox_values or {})
        self.text_values = dict(text_values or {})
        self.session_state = {}
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
        self.widget_keys.append(kwargs.get("key"))
        return self.text_values.get(label, value)

    def text_area(self, label, value="", **kwargs):
        self.text_area_labels.append(label)
        return value

    def selectbox(
        self, label, options, index=0, format_func=None, **kwargs
    ):
        self.selectbox_labels.append(label)
        self.widget_keys.append(kwargs.get("key"))
        return self.selectbox_values.get(label, options[index])

    def checkbox(self, label, value=False, key=None, **kwargs):
        self.checkbox_labels.append(label)
        self.widget_keys.append(key)
        return key in self.checked

    def radio(self, label, options, index=0, key=None, **kwargs):
        self.radio_labels.append(label)
        self.widget_keys.append(key)
        return options[index]

    def metric(self, label, value, **kwargs):
        return None

    def spinner(self, text):
        return self

    def button(self, label, key=None, **kwargs):
        self.button_keys.append(key)
        self.widget_keys.append(key)
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


def test_prepend_hides_find_and_occurrence_controls(monkeypatch):
    fake = FakeStreamlit(
        selectbox_values={"What should it change?": "prepend"}
    )
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert "Find" not in fake.text_input_labels
    assert "First or every match?" not in fake.radio_labels
    assert params["match_mode"] == "none"
    assert params["find"] == ""


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
    first = FakeStreamlit()
    renderer = _renderer(monkeypatch, first)
    renderer.render_guided_find_replace_params(params, key_prefix="op_0")
    assert params["match_mode"] == "raw_regex"
    assert params["find"] == r"^(TFeba)(\d+)$"
    assert any("discard" in text.lower() for text in first.warnings)

    confirmed = FakeStreamlit(pressed={"op_0_mode_switch_discard"})
    renderer = _renderer(monkeypatch, confirmed)
    renderer.render_guided_find_replace_params(
        params, key_prefix="op_0"
    )
    assert params["match_mode"] == "contains"
    assert params["find"] == ""


def test_guided_widget_keys_are_unique_and_operation_scoped(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)

    renderer.render_guided_find_replace_params(
        _guided_operation()["params"], key_prefix="op_0"
    )

    keys = [key for key in fake.widget_keys if key is not None]
    assert len(keys) == len(set(keys))
    assert all(key.startswith("op_0_") for key in keys)


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
