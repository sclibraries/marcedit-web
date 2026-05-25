"""Tests for marcedit_web.lib.fixed_field_008 (TASK-031)."""

from __future__ import annotations

import pymarc
import pytest

from marcedit_web.lib import fixed_field_008 as ff


# ---------------------------------------------------------------------------
# Material-type detection
# ---------------------------------------------------------------------------


def _record_with_leader(leader_text: str) -> pymarc.Record:
    rec = pymarc.Record()
    rec.leader = pymarc.Leader(leader_text)
    return rec


def test_material_type_bk_for_text_monograph():
    """Leader 06=a (language material), 07=m (monograph) → BK."""
    rec = _record_with_leader("00000nam a2200000 a 4500")
    assert ff.material_type_for(rec) == "BK"


def test_material_type_cr_for_serial():
    """Leader 07=s (serial) → CR regardless of 06."""
    rec = _record_with_leader("00000nas a2200000 a 4500")
    assert ff.material_type_for(rec) == "CR"


def test_material_type_cr_for_integrating_resource():
    """Leader 07=i (integrating resource) → CR."""
    rec = _record_with_leader("00000nai a2200000 a 4500")
    assert ff.material_type_for(rec) == "CR"


def test_material_type_other_returns_none():
    """Music (06=c, 07=m) is not in v1 scope → None."""
    rec = _record_with_leader("00000ncm a2200000 a 4500")
    assert ff.material_type_for(rec) is None


def test_material_type_unknown_combination_returns_none():
    """Leader 06=p (mixed materials), 07=c (collection) — out of scope."""
    rec = _record_with_leader("00000npc a2200000 a 4500")
    assert ff.material_type_for(rec) is None


# ---------------------------------------------------------------------------
# Schema integrity — each schema must cover bytes 0–39 with no gaps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("material", list(ff.MATERIAL_SCHEMAS))
def test_schema_covers_40_bytes_no_gaps(material):
    """Walk the schema; expect contiguous coverage of bytes 0–39."""
    schema = ff.MATERIAL_SCHEMAS[material]
    cursor = 0
    for pos in schema:
        assert pos.start == cursor, (
            f"{material}: gap or overlap at byte {cursor} (position "
            f"{pos.label!r} starts at {pos.start})"
        )
        cursor = pos.end
    assert cursor == 40, f"{material}: schema ends at byte {cursor}, expected 40"


# ---------------------------------------------------------------------------
# parse_008
# ---------------------------------------------------------------------------


def test_parse_008_returns_positions_for_book(record):
    """The sample fixture is a Books record (06=a, 07=m)."""
    material, parsed = ff.parse_008(record)
    assert material == "BK"
    assert len(parsed) == len(ff.MATERIAL_SCHEMAS["BK"])

    # Date entered on file is bytes 00-05 — the fixture's 008 starts
    # with "180706" so the parsed value should match.
    head = parsed[0]
    assert head.position.id == "008_0"
    assert head.value == "180706"


def test_parse_008_form_of_item_position(record):
    """The fixture's 008 has 'o' at byte 23 (form of item = online)."""
    _, parsed = ff.parse_008(record)
    form_pos = next(p for p in parsed if p.position.id == "008_23")
    assert form_pos.value == "o"


def test_parse_008_returns_empty_for_unhandled_material():
    """Music records aren't in v1 scope — material is None."""
    rec = _record_with_leader("00000ncm a2200000 a 4500")
    rec.add_field(pymarc.Field(tag="008", data="0" * 40))
    material, parsed = ff.parse_008(rec)
    assert material is None
    assert parsed == []


def test_parse_008_handles_missing_008(make_record):
    """Record with leader but no 008 → material code returned, parsed empty."""
    rec = make_record()
    rec.remove_fields("008")
    material, parsed = ff.parse_008(rec)
    assert material == "BK"
    assert parsed == []


def test_parse_008_pads_truncated_008(make_record):
    """A short 008 string should still parse without raising."""
    rec = make_record()
    rec.remove_fields("008")
    rec.add_field(pymarc.Field(tag="008", data="180706"))  # 6 bytes only
    _, parsed = ff.parse_008(rec)
    # Every position is present, padded out.
    assert len(parsed) == len(ff.MATERIAL_SCHEMAS["BK"])
    # The Date 1 position (bytes 7-10) should be spaces (pad).
    date1 = next(p for p in parsed if p.position.id == "008_7")
    assert date1.value == "    "


# ---------------------------------------------------------------------------
# apply_008
# ---------------------------------------------------------------------------


def test_apply_008_round_trip_unchanged(record):
    """Recomposing with parsed values produces identical bytes."""
    _, parsed = ff.parse_008(record)
    updates = {p.position.id: p.value for p in parsed}
    before = record.get("008").data
    ff.apply_008(record, updates)
    after = record.get("008").data
    assert after == before


def test_apply_008_changes_single_position(record):
    """Flip form-of-item from 'o' to ' ' and confirm only that byte changed."""
    before = record.get("008").data
    ff.apply_008(record, {"008_23": " "})
    after = record.get("008").data
    assert after[:23] == before[:23]
    assert after[23] == " "
    assert after[24:] == before[24:]


def test_apply_008_rejects_wrong_length(record):
    """Supplying a value of the wrong length raises before mutation."""
    before = record.get("008").data
    with pytest.raises(ValueError) as exc:
        ff.apply_008(record, {"008_7": "20"})  # Date 1 is 4 chars
    assert "expected 4" in str(exc.value)
    # No mutation occurred.
    assert record.get("008").data == before


def test_apply_008_rejects_disallowed_enum_value(record):
    """Supplying an unlisted enum value raises before mutation."""
    before = record.get("008").data
    with pytest.raises(ValueError) as exc:
        ff.apply_008(record, {"008_23": "X"})  # 'X' not in form-of-item set
    assert "isn't an allowed value" in str(exc.value)
    assert record.get("008").data == before


def test_apply_008_unhandled_material_raises(make_record):
    rec = make_record()
    rec.leader = pymarc.Leader("00000ncm a2200000 a 4500")  # music
    with pytest.raises(ValueError) as exc:
        ff.apply_008(rec, {"008_23": " "})
    assert "isn't handled" in str(exc.value)


def test_apply_008_adds_008_if_missing(make_record):
    """Apply works on a record without any 008 — adds one."""
    rec = make_record()
    rec.remove_fields("008")
    # Build a full updates dict using each position's existing chunk
    # (defaults to padding spaces for missing 008).
    _, parsed = ff.parse_008(rec)
    updates = {p.position.id: p.value for p in parsed}
    # Set form-of-item explicitly so the result has an inspectable byte.
    updates["008_23"] = "o"
    ff.apply_008(rec, updates)
    assert rec.get("008") is not None
    assert len(rec.get("008").data) == 40
    assert rec.get("008").data[23] == "o"


def test_apply_008_recomposed_length_invariant(record):
    """No matter what positions we set, the resulting 008 is exactly 40 bytes."""
    ff.apply_008(record, {"008_15": "xxu", "008_22": "f", "008_23": "s"})
    assert len(record.get("008").data) == 40


# ---------------------------------------------------------------------------
# Continuing Resources — light coverage just to confirm the schema swap
# ---------------------------------------------------------------------------


def test_cr_schema_has_frequency_position():
    """CR schema starts the middle section at position 18 with Frequency."""
    schema = ff.MATERIAL_SCHEMAS["CR"]
    mid = next(p for p in schema if p.start == 18)
    assert mid.label == "Frequency"


def test_apply_008_on_serial_record():
    """Apply works on a CR record with a CR-shaped 008."""
    rec = _record_with_leader("00000nas a2200000 a 4500")
    rec.add_field(pymarc.Field(tag="008", data="180706c20262026nyu m       0   0eng d"))
    ff.apply_008(rec, {"008_18": "w"})  # frequency = weekly
    assert rec.get("008").data[18] == "w"
