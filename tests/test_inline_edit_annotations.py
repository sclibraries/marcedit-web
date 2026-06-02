"""Tests for the inline `.mrk` editor's Ace gutter annotations (TASK-057).

The annotations builder is pure — input is the editor buffer text +
a ``SingleRecordParseResult`` from
``view_edit.parse_and_validate_single_record``, output is a list of
``{row, column, type, text}`` dicts the ``st_ace`` widget consumes
straight through. We unit-test it without booting Streamlit.
"""

from __future__ import annotations

import pytest

from marcedit_web.lib import view_edit
from marcedit_web.lib.mrk_annotations import (
    build_annotations as _build_annotations,
    editor_row_for_tag as _editor_row_for_tag,
)
from marcedit_web.lib.rules import parse_rules_text


# ---------------------------------------------------------------------------
# _editor_row_for_tag
# ---------------------------------------------------------------------------


_MRK_BUFFER = (
    "=LDR  00160nam a2200073 a 4500\n"
    "=001  rec-a\n"
    "=008  180706s2013    nyu     ob    001 0 eng d\n"
    "=035  \\\\$a(OCoLC)111\n"
    "=245  10$aFirst copy of dup-A"
)


def test_editor_row_for_tag_finds_control_field():
    # 001 sits on row index 1 (0-based) in the sample buffer.
    assert _editor_row_for_tag(_MRK_BUFFER, "001") == 1


def test_editor_row_for_tag_finds_variable_field():
    # 245 is the last line (row 4).
    assert _editor_row_for_tag(_MRK_BUFFER, "245") == 4


def test_editor_row_for_tag_finds_leader():
    # The leader uses ``=LDR`` not a 3-digit tag — the same prefix-
    # matching helper has to handle it.
    assert _editor_row_for_tag(_MRK_BUFFER, "LDR") == 0


def test_editor_row_for_tag_returns_none_when_absent():
    # ``856`` isn't in the buffer — the cataloger has to add it.
    assert _editor_row_for_tag(_MRK_BUFFER, "856") is None


def test_editor_row_for_tag_does_not_match_partial_prefix():
    # ``00`` is a prefix of ``001`` / ``008`` but the matcher requires
    # the tag itself to be followed by whitespace or end-of-line.
    assert _editor_row_for_tag(_MRK_BUFFER, "00") is None


# ---------------------------------------------------------------------------
# _build_annotations
# ---------------------------------------------------------------------------


@pytest.fixture
def rule_set():
    text = (
        "245\t1\tOne 245 required.\n"
        "\n"
        "001\tNR\tCONTROL NUMBER\n"
        "ind1\tblank\tUndefined\n"
        "ind2\tblank\tUndefined\n"
        "\n"
        "245\tNR\tTITLE STATEMENT\n"
        "ind1\t01\tTitle added entry\n"
        "ind2\t0-9\tNonfiling characters\n"
        "subfield\tabc\tValid Subfields\n"
        "a\tNR\tTitle\n"
    )
    rs, warnings = parse_rules_text(text)
    assert warnings == []
    return rs


def test_build_annotations_returns_empty_when_no_result():
    # The render path passes ``None`` when the buffer is empty.
    assert _build_annotations("", None) == []


def test_build_annotations_surfaces_parser_error_with_exact_line():
    # ``=invalid`` has no leader line and an unrecognized tag — the
    # parser emits a ``LineError`` carrying line_no=1.
    buffer = "=XYZ  not a real tag"
    result = view_edit.parse_and_validate_single_record(buffer, None)
    annotations = _build_annotations(buffer, result)
    # At least one annotation must point at row 0 (line_no=1 - 1)
    # with an error type, because parse_and_validate flags this
    # buffer as fatally broken.
    assert annotations, "expected at least one parser annotation"
    assert any(a["row"] == 0 and a["type"] == "error" for a in annotations)


def test_build_annotations_anchors_rule_warning_to_matching_tag(rule_set):
    # 245 ind1='5' is not in the rule set's allowed indicators ({0, 1}),
    # so rules_validate emits a ``rule-bad-indicator`` warning on the
    # 245 line. The annotation should anchor at row 4 (the =245 line),
    # not row 0.
    buffer = (
        "=LDR  00160nam a2200073 a 4500\n"
        "=001  rec-a\n"
        "=008  180706s2013    nyu     ob    001 0 eng d\n"
        "=035  \\\\$a(OCoLC)111\n"
        "=245  50$aTitle with bad indicator"
    )
    result = view_edit.parse_and_validate_single_record(buffer, rule_set)
    annotations = _build_annotations(buffer, result)
    rule_warnings = [
        a for a in annotations
        if a["type"] == "warning" and "rule-bad-indicator" in a["text"]
    ]
    assert rule_warnings, f"no rule-bad-indicator annotation; got {annotations}"
    assert rule_warnings[0]["row"] == 4


def test_build_annotations_anchors_missing_field_at_row_zero(rule_set):
    # Buffer has no 245 but the rule set requires one; ``rule-missing-245``
    # fires. Since there's no ``=245`` line to anchor to, the helper
    # defaults to row 0 so the marker is still visible.
    buffer = (
        "=LDR  00160nam a2200073 a 4500\n"
        "=001  rec-a\n"
        "=008  180706s2013    nyu     ob    001 0 eng d"
    )
    result = view_edit.parse_and_validate_single_record(buffer, rule_set)
    annotations = _build_annotations(buffer, result)
    missing_245 = [
        a for a in annotations
        if "missing-245" in a["text"] or "rule-missing-245" in a["text"]
    ]
    assert missing_245, f"no missing-245 annotation; got {annotations}"
    assert missing_245[0]["row"] == 0


def test_build_annotations_dict_shape_matches_st_ace_contract():
    # st_ace consumes dicts with exactly these four keys; the test
    # guards against an accidental typo or renamed field.
    buffer = "=XYZ  garbage"
    result = view_edit.parse_and_validate_single_record(buffer, None)
    annotations = _build_annotations(buffer, result)
    assert annotations
    for ann in annotations:
        assert set(ann.keys()) == {"row", "column", "type", "text"}
        assert isinstance(ann["row"], int) and ann["row"] >= 0
        assert isinstance(ann["column"], int) and ann["column"] >= 0
        assert ann["type"] in {"error", "warning", "info"}
        assert isinstance(ann["text"], str) and ann["text"]
