"""Tests for structured LDR / 006 / 007 fixed-field editing."""

from __future__ import annotations

import pymarc
import pytest

from marcedit_web.lib import fixed_field_control as ffc


def _record_with_006_007(make_record):
    record = make_record()
    record.add_field(pymarc.Field(tag="006", data="m     o  d        "))
    record.add_field(pymarc.Field(tag="007", data="cr cn|||||||||"))
    return record


def test_parse_fixed_fields_labels_leader_positions(make_record):
    """Leader bytes should be editable by label, not by raw byte counting."""
    record = make_record()

    parsed = ffc.parse_fixed_fields(record)

    leader = parsed["LDR"]
    type_of_record = next(pos for pos in leader if pos.id == "LDR_6")
    bib_level = next(pos for pos in leader if pos.id == "LDR_7")
    assert type_of_record.label == "Type of record"
    assert type_of_record.value == "a"
    assert bib_level.label == "Bibliographic level"
    assert bib_level.value == "m"


def test_parse_fixed_fields_labels_006_and_007_positions(make_record):
    """006/007 helpers should expose cataloger-readable position labels."""
    record = _record_with_006_007(make_record)

    parsed = ffc.parse_fixed_fields(record)

    form_of_item = next(pos for pos in parsed["006"] if pos.id == "006_6")
    category = next(pos for pos in parsed["007"] if pos.id == "007_0")
    smd = next(pos for pos in parsed["007"] if pos.id == "007_1")
    assert form_of_item.label == "Form of item"
    assert form_of_item.value == "o"
    assert category.label == "Category of material"
    assert category.value == "c"
    assert smd.label == "Specific material designation"
    assert smd.value == "r"


def test_apply_fixed_field_updates_leader_without_changing_length(make_record):
    """Saving a structured LDR edit should preserve the 24-byte leader."""
    record = make_record()

    ffc.apply_fixed_field_updates(record, {"LDR_17": "3"})

    assert str(record.leader)[17] == "3"
    assert len(str(record.leader)) == 24


def test_apply_fixed_field_updates_006_and_007(make_record):
    """Structured fixed-field edits should mutate only the selected bytes."""
    record = _record_with_006_007(make_record)
    before_006 = record["006"].data
    before_007 = record["007"].data

    ffc.apply_fixed_field_updates(record, {"006_6": "s", "007_1": "z"})

    assert record["006"].data[:6] == before_006[:6]
    assert record["006"].data[6] == "s"
    assert record["006"].data[7:] == before_006[7:]
    assert record["007"].data[0] == before_007[0]
    assert record["007"].data[1] == "z"
    assert record["007"].data[2:] == before_007[2:]


def test_apply_fixed_field_rejects_bad_position_value(make_record):
    """A single-byte position must reject multi-character input before mutation."""
    record = _record_with_006_007(make_record)
    before = record["006"].data

    with pytest.raises(ValueError) as exc:
        ffc.apply_fixed_field_updates(record, {"006_6": "online"})

    assert "expected 1" in str(exc.value)
    assert record["006"].data == before
