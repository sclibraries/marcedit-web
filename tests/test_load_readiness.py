"""Tests for the FOLIO / EDS CC load-readiness warning profile."""

from __future__ import annotations

from pymarc import Field, Subfield

from marcedit_web.lib import load_readiness


def _add_load_ready_fields(record) -> None:
    record.add_field(Field(tag="006", data="m     o  d        "))
    record.add_field(Field(tag="007", data="cr cn|||||||||"))
    for tag, label, code, source in (
        ("336", "text", "txt", "rdacontent"),
        ("337", "computer", "c", "rdamedia"),
        ("338", "online resource", "cr", "rdacarrier"),
    ):
        record.add_field(
            Field(
                tag=tag,
                indicators=[" ", " "],
                subfields=[
                    Subfield("a", label),
                    Subfield("b", code),
                    Subfield("2", source),
                ],
            )
        )


def _codes(record) -> set[str]:
    return {issue.code for issue in load_readiness.validate_records([record])}


def test_load_readiness_accepts_expected_shared_folio_eds_fields(make_record):
    """A record with the shared FOLIO/EDS CC prerequisites stays quiet."""
    record = make_record()
    _add_load_ready_fields(record)

    assert _codes(record) == set()


def test_load_readiness_flags_missing_fixed_fields(make_record):
    """006 and 007 must be visibly called out for load review."""
    record = make_record()

    codes = _codes(record)

    assert "load-missing-006" in codes
    assert "load-missing-007" in codes


def test_load_readiness_flags_invalid_fixed_field_lengths(make_record):
    """Fixed fields that exist but are structurally wrong are warnings."""
    record = make_record()
    _add_load_ready_fields(record)
    record.remove_fields("006", "007")
    record.add_field(Field(tag="006", data="too-short"))
    record.add_field(Field(tag="007", data="cr"))

    codes = _codes(record)

    assert "load-invalid-006" in codes
    assert "load-invalid-007" in codes


def test_load_readiness_flags_008_form_of_item_not_online(make_record):
    """008 byte 23 should be explicit: 'o' for online, not 's'."""
    record = make_record()
    _add_load_ready_fields(record)
    f008 = record["008"]
    data = list(f008.data)
    data[23] = "s"
    f008.data = "".join(data)

    issues = load_readiness.validate_records([record])

    assert [issue.code for issue in issues] == ["load-008-form-of-item"]
    assert "byte 23 is 's'" in issues[0].message


def test_load_readiness_flags_rda_fields_missing_b(make_record):
    """336/337/338 must include code subfield $b for load review."""
    record = make_record()
    _add_load_ready_fields(record)
    record.remove_fields("337")
    record.add_field(
        Field(
            tag="337",
            indicators=[" ", " "],
            subfields=[
                Subfield("a", "computer"),
                Subfield("2", "rdamedia"),
            ],
        )
    )

    codes = _codes(record)

    assert codes == {"load-missing-rda-b"}
