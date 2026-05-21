"""Tests for marcedit_web.lib.transforms (generic helpers, post-Smith strip)."""

from __future__ import annotations

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
