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
