"""Tests for marcedit_web.lib.viewer."""

from __future__ import annotations

import pytest

from marcedit_web.lib import viewer


def test_parse_indices_simple():
    assert viewer.parse_indices("1") == {1}
    assert viewer.parse_indices("1,3,5") == {1, 3, 5}
    assert viewer.parse_indices("1-3") == {1, 2, 3}
    assert viewer.parse_indices("1-3,7,9-10") == {1, 2, 3, 7, 9, 10}


def test_parse_indices_rejects_empty():
    with pytest.raises(ValueError):
        viewer.parse_indices("")


def test_parse_fields_accepts_commas_and_spaces():
    assert viewer.parse_fields("856") == {"856"}
    assert viewer.parse_fields("035,856") == {"035", "856"}
    assert viewer.parse_fields("035 856") == {"035", "856"}


def test_parse_fields_rejects_non_tag():
    with pytest.raises(ValueError):
        viewer.parse_fields("abcd")


def test_render_record_full(record):
    text = viewer.render_record(record)
    assert "=001" in text
    assert "=245" in text
    assert "=856" in text


def test_render_record_filter(record):
    text = viewer.render_record(record, fields={"245", "856"})
    assert "=245" in text
    assert "=856" in text
    assert "=001" not in text
    assert "=029" not in text


def test_render_record_includes_leader_when_requested(record):
    text = viewer.render_record(record, fields={"LDR"})
    assert text.startswith("=LDR  ")


def test_record_title_strips_punctuation(record):
    assert viewer.record_title(record) == "Test title"


def test_record_identifier_prefers_001(record):
    assert viewer.record_identifier(record) == "1234567890"


def test_record_identifier_falls_back_to_035(record):
    import pymarc

    record.remove_fields("001")
    record.add_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", "(OCoLC)999")],
        )
    )
    assert viewer.record_identifier(record) == "(OCoLC)999"


def test_record_identifier_returns_dash_when_missing(record):
    record.remove_fields("001")
    record.remove_fields("035")
    assert viewer.record_identifier(record) == "-"


def test_cli_paths_are_gone():
    """`view()` and `diff()` were CLI-only and should be removed."""
    assert not hasattr(viewer, "view")
    assert not hasattr(viewer, "diff")
    assert not hasattr(viewer, "_GREEN")
