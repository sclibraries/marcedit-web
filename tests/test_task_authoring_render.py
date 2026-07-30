"""Focused widget-contract tests for structured task authoring."""

from __future__ import annotations

from pymarc import Field, Record


class FakeStreamlit:
    def __init__(self, pressed=None):
        self.pressed = set(pressed or ())
        self.text_input_labels = []
        self.text_area_labels = []
        self.selectbox_labels = []
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
        return value

    def text_area(self, label, value="", **kwargs):
        self.text_area_labels.append(label)
        return value

    def selectbox(
        self, label, options, index=0, format_func=None, **kwargs
    ):
        self.selectbox_labels.append(label)
        return options[index]

    def button(self, label, key=None, **kwargs):
        self.button_keys.append(key)
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
