"""Tests for MarcEditor tab mode selection."""

from __future__ import annotations

from marcedit_web.render import edit


def test_marceditor_defaults_to_record_editor_under_source_cap():
    """Catalogers should not land in full-batch `.mrk` source by default."""
    assert edit._default_editor_mode(edit.MAX_EDITOR_RECORDS) == edit.RECORD_MODE


def test_marceditor_source_mode_available_under_cap():
    modes = edit._editor_mode_options(edit.MAX_EDITOR_RECORDS)

    assert modes == [edit.RECORD_MODE, edit.SOURCE_MODE]


def test_marceditor_source_mode_hidden_over_cap():
    modes = edit._editor_mode_options(edit.MAX_EDITOR_RECORDS + 1)

    assert modes == [edit.RECORD_MODE]


def test_marceditor_record_picker_opens_editor_directly(monkeypatch, record):
    """The primary MarcEditor record view should be editable immediately."""
    calls = []
    monkeypatch.setattr(edit.viewer, "record_identifier", lambda record: "id")
    monkeypatch.setattr(edit.viewer, "record_title", lambda record: "Title")
    monkeypatch.setattr(edit.viewer, "render_record_human", lambda record: "raw")
    monkeypatch.setattr(edit.st, "session_state", {edit._K_PICK_INDEX: 1})
    monkeypatch.setattr(
        edit.st,
        "columns",
        lambda spec: [_Column() for _ in spec],
    )
    monkeypatch.setattr(edit.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(edit.st, "expander", lambda *args, **kwargs: _Context())
    monkeypatch.setattr(edit.st, "code", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        edit.single_record_edit,
        "render_inline_edit",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        edit.fixed_field_helper,
        "render_fixed_field_helper",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        edit.fixed_field_helper,
        "render_008_helper",
        lambda **kwargs: None,
    )

    edit._render_single_record_picker(_Store(record), 1, rule_set=None)

    assert calls[0]["start_open"] is True


class _Store:
    def __init__(self, record):
        self._record = record

    def get(self, index):
        assert index == 0
        return self._record


class _Column:
    def button(self, *args, **kwargs):
        return False

    def number_input(self, *args, **kwargs):
        return 1


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
