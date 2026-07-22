"""Tests for marcedit_web.lib.viewer."""

from __future__ import annotations

import pytest
from pymarc import Field, Record, Subfield

from marcedit_web.lib import viewer


def _record_with_tags(*tags: str) -> Record:
    record = Record()
    for tag in tags:
        if tag < "010":
            record.add_field(Field(tag=tag, data=f"value-{tag}"))
        else:
            record.add_field(
                Field(
                    tag=tag,
                    indicators=[" ", " "],
                    subfields=[Subfield("a", f"value-{tag}")],
                )
            )
    return record


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


def test_field_order_inversions_is_silent_for_ascending_and_repeated_tags():
    record = _record_with_tags("001", "035", "035", "040", "245")

    assert viewer.field_order_inversions(record) == []


def test_field_order_inversions_reports_adjacent_descending_tags():
    record = _record_with_tags("001", "040", "035", "245")

    assert viewer.field_order_inversions(record) == [("040", "035")]


def test_field_order_inversions_respects_limit():
    record = _record_with_tags("009", "008", "007", "006", "005")

    assert viewer.field_order_inversions(record, limit=3) == [
        ("009", "008"),
        ("008", "007"),
        ("007", "006"),
    ]


def test_field_order_inversions_does_not_mutate_record_bytes():
    record = _record_with_tags("001", "040", "035", "245")
    before = record.as_marc()

    viewer.field_order_inversions(record)

    assert record.as_marc() == before


def test_render_record_human_preserves_source_field_order():
    record = _record_with_tags("001", "040", "035", "245")

    text = viewer.render_record_human(record)

    offsets = [text.index(f"={tag}") for tag in ("001", "040", "035", "245")]
    assert offsets == sorted(offsets)


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


# ---------------------------------------------------------------------------
# render_record_human — TASK-026 human-readable display
# ---------------------------------------------------------------------------


def test_render_record_human_uses_real_spaces_in_control_fields(record):
    """008 spaces render as spaces, not `\\`.

    The fixture's 008 is exactly 40 bytes including real spaces; the
    .mrk renderer would have substituted each space with ``\\``.
    """
    text = viewer.render_record_human(record)
    # The 008 in the fixture is "180706s2013    nyu     ob    001 0 eng d"
    # — runs of real spaces around the place code and material fields.
    assert "=008  180706s2013    nyu     ob    001 0 eng d" in text


def test_render_record_human_preserves_pipes(record):
    """Pipe characters (`|` is MARC fill) come through verbatim."""
    import pymarc

    record.remove_fields("007")
    record.add_field(pymarc.Field(tag="007", data="cr|mn|||||||||"))
    text = viewer.render_record_human(record)
    assert "=007  cr|mn|||||||||" in text


def test_render_record_human_uses_double_dagger_for_subfield_delim(record):
    """Subfield delimiter (byte 0x1F) renders as `‡`, not `$`."""
    text = viewer.render_record_human(record)
    # The fixture's 245 has $a "Test title."
    assert "‡aTest title." in text
    # And `$` MUST NOT appear in the 245 line as a subfield delim — only
    # ‡ should be the delimiter glyph there.
    line_245 = next(
        line for line in text.splitlines() if line.startswith("=245")
    )
    # Indicators are "1" + "0" + "‡a..." — the dollar sign should be
    # absent unless the subfield value itself contained one.
    assert "$" not in line_245


def test_render_record_human_does_not_escape_blank_indicators(record):
    """Blank indicators render as actual spaces, not `\\`.

    The fixture's 506 has both indicators blank. In the .mrk shape
    that's ``=506  \\\\$a...``; in the human shape it's just two
    spaces between the tag and the subfield delim.
    """
    text = viewer.render_record_human(record)
    line_506 = next(
        line for line in text.splitlines() if line.startswith("=506")
    )
    # The `=506  ` prefix is 6 characters (tag + 2 spaces). Then the
    # two blank indicators are 2 actual spaces. Then ‡a.
    assert line_506.startswith("=506    ‡a")
    assert "\\" not in line_506


def test_render_record_human_filter_excludes_unwanted_tags(record):
    text = viewer.render_record_human(record, fields={"245", "856"})
    assert "=245" in text
    assert "=856" in text
    assert "=001" not in text
    assert "=029" not in text


def test_render_record_human_leader_renders_cleanly(record):
    text = viewer.render_record_human(record, fields={"LDR"})
    assert text.startswith("=LDR  ")
    # Single line when filtered to just the leader.
    assert "\n" not in text


def test_render_record_human_subfield_value_with_dollar_sign_is_unambiguous(record):
    """A `$` inside subfield data doesn't get treated as a delimiter."""
    import pymarc

    record.remove_fields("020")
    record.add_field(pymarc.Field(
        tag="020",
        indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "price $19.99")],
    ))
    text = viewer.render_record_human(record)
    line_020 = next(
        line for line in text.splitlines() if line.startswith("=020")
    )
    # Exactly one `‡` (the delim before `a`); the `$` inside the value
    # stays as a `$` and is not confused for another subfield.
    assert line_020.count("‡") == 1
    assert "$19.99" in line_020
