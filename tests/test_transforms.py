"""Tests for marcedit_web.lib.transforms (generic helpers, post-Smith strip)."""

from __future__ import annotations

import re

import pymarc
import pytest

from marcedit_web.lib import transforms


def test_leader_type_and_biblevel(record):
    assert transforms.leader_type(record) == "a"
    assert transforms.leader_biblevel(record) == "m"


def test_set_008_form_of_item_writes_byte_23(record):
    transforms.set_008_form_of_item(record, "q")
    assert record.get("008").data[23] == "q"


def test_set_008_form_of_item_skips_unknown_leader(record):
    record.leader = pymarc.Leader("00000nzz a2200000 a 4500")
    before = record.get("008").data
    transforms.set_008_form_of_item(record, "o")
    assert record.get("008").data == before


def test_delete_tags_exact(record):
    assert record.get("029") is not None
    transforms.delete_tags(record, "029")
    assert record.get("029") is None
    # 891 not deleted
    assert record.get("891") is not None


def test_delete_tags_wildcard(record):
    transforms.delete_tags(record, "8XX")  # deletes 800-899
    assert record.get("856") is None
    assert record.get("891") is None
    # Non-8xx still present
    assert record.get("245") is not None


def test_delete_fields_matching_subfield(record):
    assert len(record.get_fields("655")) == 1
    transforms.delete_fields_matching_subfield(record, "655", "a", "Electronic")
    assert record.get_fields("655") == []


def test_delete_856_fields_matching_url_only_touches_856(record):
    transforms.delete_856_fields_matching_url(record, "example.org/ebook")
    urls = [
        sf.value
        for f in record.get_fields("856")
        for sf in f.subfields
        if sf.code == "u"
    ]
    assert urls == ["https://example.org/related/12345"]


def test_delete_856_fields_matching_url_regex(record):
    transforms.delete_856_fields_matching_url_regex(record, r"/related/")
    urls = [
        sf.value
        for f in record.get_fields("856")
        for sf in f.subfields
        if sf.code == "u"
    ]
    assert urls == ["https://example.org/ebook/12345"]


def test_make_field_normalizes_backslash_indicator():
    f = transforms.make_field("245", "\\", "0", ("a", "Title"))
    assert f.tag == "245"
    # pymarc 5 returns Indicators (namedtuple-like) for f.indicators.
    assert list(f.indicators) == [" ", "0"]
    assert f.get_subfields("a") == ["Title"]


def test_add_field_if_absent_dedupes(record):
    new = transforms.make_field("245", "1", "0", ("a", "Test title."))
    added = transforms.add_field_if_absent(record, new)
    assert added is False
    # A field with a different subfield value is treated as distinct.
    new2 = transforms.make_field("245", "1", "0", ("a", "Different title."))
    added2 = transforms.add_field_if_absent(record, new2)
    assert added2 is True


def test_sort_fields_orders_by_tag(record):
    transforms.sort_fields(record)
    tags = [f.tag for f in record.fields]
    assert tags == sorted(tags)


def test_control_value(record):
    assert transforms.control_value(record, "001") == "1234567890"
    assert transforms.control_value(record, "999") is None


def test_dedupe_035_removes_exact_duplicate(record):
    sf = pymarc.Subfield("a", "(OCoLC)1234567890")
    record.add_field(pymarc.Field(tag="035", indicators=[" ", " "], subfields=[sf]))
    record.add_field(pymarc.Field(tag="035", indicators=[" ", " "], subfields=[sf]))
    assert len(record.get_fields("035")) == 2
    transforms.dedupe_035(record)
    assert len(record.get_fields("035")) == 1


# ---------------------------------------------------------------------------
# TASK-030: Task Builder ops expansion
# ---------------------------------------------------------------------------


def test_copy_field_duplicates_with_same_data(record):
    """Copy 856 → 956 leaves 856 in place and adds matching 956 fields."""
    src_count = len(record.get_fields("856"))
    assert src_count > 0
    transforms.copy_field(record, "856", "956")
    assert len(record.get_fields("856")) == src_count  # source untouched
    new_fields = record.get_fields("956")
    assert len(new_fields) == src_count
    # Subfields/indicators round-trip.
    for src, dst in zip(record.get_fields("856"), new_fields):
        assert dst.indicators == src.indicators
        assert [(sf.code, sf.value) for sf in dst.subfields] == [
            (sf.code, sf.value) for sf in src.subfields
        ]


def test_copy_field_handles_control_field(record):
    """Control fields use ``.data`` rather than indicators + subfields."""
    transforms.copy_field(record, "001", "010")
    f010 = record.get("010")
    # ``010`` is variable in our rule set but the copy honors the source
    # shape — a control-field copy keeps ``.data``.
    assert f010 is not None


def test_copy_field_noop_on_missing_source(make_record):
    """No source matches → no destination added."""
    record = make_record()
    transforms.copy_field(record, "999", "888")
    assert record.get("888") is None


def test_move_field_retag_and_drop_source(record):
    src_count = len(record.get_fields("856"))
    transforms.move_field(record, "856", "956")
    assert record.get_fields("856") == []
    assert len(record.get_fields("956")) == src_count


def test_move_field_same_tag_is_noop(record):
    """src == dst short-circuits without touching anything."""
    before = [
        (f.tag, list(f.indicators), [(sf.code, sf.value) for sf in f.subfields])
        for f in record.get_fields("856")
    ]
    transforms.move_field(record, "856", "856")
    after = [
        (f.tag, list(f.indicators), [(sf.code, sf.value) for sf in f.subfields])
        for f in record.get_fields("856")
    ]
    assert before == after


def test_add_subfield_to_fields_appends_by_default(record):
    transforms.add_subfield_to_fields(record, "655", "2", "fast")
    f655 = record.get_fields("655")[0]
    codes = [sf.code for sf in f655.subfields]
    # ``2`` was already on the fixture's 655; this appends another.
    assert codes[-1] == "2"


def test_add_subfield_to_fields_prepend_position(record):
    transforms.add_subfield_to_fields(record, "655", "9", "LOCAL", position="start")
    f655 = record.get_fields("655")[0]
    assert f655.subfields[0].code == "9"
    assert f655.subfields[0].value == "LOCAL"


def test_add_subfield_skips_control_fields(record):
    """Asking to add to 001 is a no-op (no subfields on control fields)."""
    before = record.get("001").data
    transforms.add_subfield_to_fields(record, "001", "a", "ignored")
    assert record.get("001").data == before


def test_delete_subfields_drops_listed_codes(record):
    """Strip $u from every 856 field."""
    assert any(sf.code == "u" for f in record.get_fields("856") for sf in f.subfields)
    transforms.delete_subfields(record, "856", "u")
    remaining = [sf.code for f in record.get_fields("856") for sf in f.subfields]
    assert "u" not in remaining


def test_delete_subfields_supports_multiple_codes(record):
    """Pass multiple codes to drop them in one call."""
    record.get_fields("856")[0].subfields.append(pymarc.Subfield("z", "note"))
    transforms.delete_subfields(record, "856", "u", "z")
    remaining = [sf.code for f in record.get_fields("856") for sf in f.subfields]
    assert "u" not in remaining
    assert "z" not in remaining


def test_delete_subfields_empty_codes_is_noop(record):
    before = [(sf.code, sf.value) for f in record.get_fields("856") for sf in f.subfields]
    transforms.delete_subfields(record, "856")
    after = [(sf.code, sf.value) for f in record.get_fields("856") for sf in f.subfields]
    assert before == after


def test_delete_subfields_matching_value_exact_only_removes_matching_subfield():
    record = pymarc.Record()
    record.add_ordered_field(
        pymarc.Field(
            tag="300",
            indicators=[" ", " "],
            subfields=[
                pymarc.Subfield("a", "1 online resource"),
                pymarc.Subfield("b", ":"),
                pymarc.Subfield("b", "illustrations"),
            ],
        )
    )

    transforms.delete_subfields_matching_value(record, "300", "b", ":")

    field = record.get_fields("300")[0]
    assert [(sf.code, sf.value) for sf in field.subfields] == [
        ("a", "1 online resource"),
        ("b", "illustrations"),
    ]


def test_delete_subfields_matching_value_contains_can_ignore_case(record):
    record.get_fields("856")[0].subfields.append(
        pymarc.Subfield("z", "Smith Proxy note")
    )
    record.get_fields("856")[0].subfields.append(
        pymarc.Subfield("z", "Public note")
    )

    transforms.delete_subfields_matching_value(
        record,
        "856",
        "z",
        "proxy",
        match="contains",
        ignore_case=True,
    )

    remaining = [
        sf.value
        for field in record.get_fields("856")
        for sf in field.subfields
        if sf.code == "z"
    ]
    assert remaining == ["Public note"]


def test_delete_subfields_matching_value_regex_trims_before_comparison():
    record = pymarc.Record()
    record.add_ordered_field(
        pymarc.Field(
            tag="500",
            indicators=[" ", " "],
            subfields=[
                pymarc.Subfield("a", "   :   "),
                pymarc.Subfield("a", " : still text"),
            ],
        )
    )

    transforms.delete_subfields_matching_value(
        record,
        "500",
        "a",
        r"^:$",
        match="regex",
        trim=True,
    )

    assert record.get_fields("500")[0].get_subfields("a") == [" : still text"]


def test_copy_subfield_within_field(record):
    """Copy $a → $z within every 245 field."""
    transforms.copy_subfield_within_field(record, "245", "a", "z")
    f245 = record.get_fields("245")[0]
    a_values = [sf.value for sf in f245.subfields if sf.code == "a"]
    z_values = [sf.value for sf in f245.subfields if sf.code == "z"]
    assert z_values == a_values  # one $z per existing $a


def test_set_indicators_overrides_both(record):
    transforms.set_indicators(record, "856", ind1="0", ind2="1")
    for f in record.get_fields("856"):
        assert list(f.indicators) == ["0", "1"]


def test_set_indicators_leave_alone_with_none(record):
    """``None`` on one side keeps the existing indicator value."""
    before = [list(f.indicators) for f in record.get_fields("856")]
    transforms.set_indicators(record, "856", ind1="7")
    for f, original in zip(record.get_fields("856"), before):
        assert f.indicators[0] == "7"
        assert f.indicators[1] == original[1]


def test_set_indicators_skips_control_fields(record):
    """Control fields have no indicators — the helper must not crash."""
    transforms.set_indicators(record, "001", ind1="0")
    # Just survives.


def test_replace_field_subfield_and_indicators_updates_only_matching_field():
    record = pymarc.Record()
    matching = pymarc.Field(
        tag="035",
        indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "TFeba")],
    )
    nonmatching_value = pymarc.Field(
        tag="035",
        indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", "OTHER")],
    )
    nonmatching_indicator = pymarc.Field(
        tag="035",
        indicators=[" ", "9"],
        subfields=[pymarc.Subfield("a", "TFeba")],
    )
    record.add_ordered_field(matching)
    record.add_ordered_field(nonmatching_value)
    record.add_ordered_field(nonmatching_indicator)

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        "TFeba",
        " ",
        "9",
        "a",
        "(SCTFEBA)",
    )

    fields = record.get_fields("035")
    assert list(fields[0].indicators) == [" ", "9"]
    assert fields[0].get_subfields("a") == ["(SCTFEBA)"]
    assert list(fields[1].indicators) == [" ", " "]
    assert fields[1].get_subfields("a") == ["OTHER"]
    assert list(fields[2].indicators) == [" ", "9"]
    assert fields[2].get_subfields("a") == ["TFeba"]


def test_replace_field_subfield_and_indicators_can_change_subfield_code():
    record = pymarc.Record()
    record.add_ordered_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", "TFeba")],
        )
    )

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        "TFeba",
        " ",
        "9",
        "z",
        "(SCTFEBA)",
    )

    field = record.get_fields("035")[0]
    assert list(field.indicators) == [" ", "9"]
    assert field.get_subfields("a") == []
    assert field.get_subfields("z") == ["(SCTFEBA)"]


def _record_with_035(*values):
    record = pymarc.Record()
    for value in values:
        record.add_ordered_field(
            pymarc.Field(
                tag="035",
                indicators=[" ", " "],
                subfields=[pymarc.Subfield("a", value)],
            )
        )
    return record


def test_replace_field_subfield_and_indicators_regex_preserves_unmatched_isbn():
    record = _record_with_035("TFeba9780020306634")

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        "TFeba",
        " ",
        "9",
        "a",
        "(SCTFEBA)",
        regex=True,
    )

    field = record.get_fields("035")[0]
    assert list(field.indicators) == [" ", "9"]
    assert field.get_subfields("a") == ["(SCTFEBA)9780020306634"]


def test_replace_field_subfield_and_indicators_regex_preserves_both_sides():
    record = _record_with_035("prefix-TFeba123-suffix")

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        r"TFeba\d+",
        " ",
        "9",
        "a",
        "replacement",
        regex=True,
    )

    field = record.get_fields("035")[0]
    assert field.get_subfields("a") == ["prefix-replacement-suffix"]


def test_replace_field_subfield_and_indicators_regex_replaces_every_match():
    record = _record_with_035("TFeba-one-TFeba-two")

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        "TFeba",
        " ",
        "9",
        "a",
        "X",
        regex=True,
    )

    assert record.get_fields("035")[0].get_subfields("a") == ["X-one-X-two"]


def test_replace_field_subfield_and_indicators_regex_expands_capture_references():
    record = _record_with_035("TFeba9780020306634")

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        r"TFeba(\d+)",
        " ",
        "9",
        "a",
        r"(SCTFEBA)\1",
        regex=True,
    )

    assert record.get_fields("035")[0].get_subfields("a") == [
        "(SCTFEBA)9780020306634"
    ]


def test_replace_field_subfield_and_indicators_regex_is_case_sensitive_by_default():
    record = pymarc.Record()
    record.add_ordered_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", "tfeba")],
        )
    )

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        "TFeba",
        " ",
        "9",
        "a",
        "replacement",
        regex=True,
    )

    field = record.get_fields("035")[0]
    assert field.get_subfields("a") == ["tfeba"]


def test_replace_field_subfield_and_indicators_regex_can_ignore_case():
    record = pymarc.Record()
    record.add_ordered_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", "prefix-tfeba123-suffix")],
        )
    )

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        r"TFeba\d+",
        " ",
        "9",
        "a",
        "replacement",
        regex=True,
        ignore_case=True,
    )

    field = record.get_fields("035")[0]
    assert field.get_subfields("a") == ["prefix-replacement-suffix"]


def test_replace_field_subfield_and_indicators_invalid_regex_does_not_mutate():
    record = pymarc.Record()
    record.add_ordered_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", "TFeba")],
        )
    )
    before = record.as_marc()

    with pytest.raises(re.error):
        transforms.replace_field_subfield_and_indicators(
            record,
            "035",
            " ",
            " ",
            "a",
            "(",
            " ",
            "9",
            "a",
            "replacement",
            regex=True,
        )

    assert record.as_marc() == before


def test_replace_field_subfield_and_indicators_invalid_reference_does_not_mutate():
    record = _record_with_035("TFeba123", "TFeba456")
    before = record.as_marc()

    with pytest.raises(re.error):
        transforms.replace_field_subfield_and_indicators(
            record,
            "035",
            " ",
            " ",
            "a",
            r"TFeba(\d+)",
            " ",
            "9",
            "a",
            r"\2",
            regex=True,
        )

    assert record.as_marc() == before


def test_replace_field_subfield_and_indicators_exact_match_stays_case_sensitive():
    record = pymarc.Record()
    record.add_ordered_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", "tfeba")],
        )
    )

    transforms.replace_field_subfield_and_indicators(
        record,
        "035",
        " ",
        " ",
        "a",
        "TFeba",
        " ",
        "9",
        "a",
        "replacement",
        regex=False,
        ignore_case=True,
    )

    field = record.get_fields("035")[0]
    assert field.get_subfields("a") == ["tfeba"]


def test_regex_replace_field_data_variable_field(record):
    """Replace text across every subfield value of a tag."""
    transforms.regex_replace_field_data(
        record, "245", r"Test", "Edited"
    )
    title = record.get_fields("245")[0]["a"]
    assert "Edited title" in title
    assert "Test title" not in title


def test_regex_replace_field_data_control_field(record):
    """Control fields edit ``.data``."""
    transforms.regex_replace_field_data(record, "001", r"^.*$", "REPLACED")
    assert record.get("001").data == "REPLACED"


def test_regex_replace_field_data_ignore_case(record):
    transforms.regex_replace_field_data(
        record, "245", r"test", "Lower", ignore_case=True
    )
    assert "Lower title" in record.get_fields("245")[0]["a"]


def test_regex_replace_field_data_empty_pattern_is_noop(record):
    before = record.get_fields("245")[0]["a"]
    transforms.regex_replace_field_data(record, "245", "", "X")
    assert record.get_fields("245")[0]["a"] == before


def test_smith_specific_helpers_are_gone():
    """libproxy / container-stamping / OCLC-035 helpers stripped per plan."""
    for name in (
        "proxy_856_full_text",
        "PROXY_PREFIX",
        "SMITH_LINK_LABEL",
        "canonicalize_oclc_035",
        "_canonicalize_oclc_a_value",
        "add_oclc_003_if_missing",
        "looks_like_vendor_001",
        "delete_856_fields_matching_url_domain",
        "_host_from_url",
    ):
        assert not hasattr(transforms, name), f"{name} should have been removed"


# ---------------------------------------------------------------------------
# TASK-078a: canonical OCLC-035 extraction (the single generic owner that
# replaces the three divergent copies; NOT the removed Smith canonicalizer).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("(OCoLC)12345", "12345"),
        ("(OCoLC)ocm00012345", "ocm00012345"),
        ("(OCoLC)ocn123456789", "ocn123456789"),
        ("(OCoLC)on1234567890", "on1234567890"),
        ("12345", None),               # bare number is NOT an OCLC number
        ("(DLC)12345", None),
        ("(OCoLC)", None),             # empty after the prefix
        ("  (OCoLC)12345", "12345"),   # leading whitespace tolerated
        ("(OCoLC)12345  ", "12345"),   # trailing whitespace stripped
        ("", None),
    ],
)
def test_normalize_oclc_035(value, expected):
    assert transforms.normalize_oclc_035(value) == expected


# TASK-078c: shared control-tag predicate (was duplicated in rules_validate + mrk_parser)


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("001", True),
        ("008", True),
        ("009", True),
        ("000", False),   # 000 is the leader sentinel, not a control field
        ("010", False),
        ("245", False),
        ("00", False),    # too short
        ("0012", False),  # too long
        ("00X", False),   # non-digit in position 2
    ],
)
def test_is_control_tag(tag, expected):
    assert transforms.is_control_tag(tag) is expected
