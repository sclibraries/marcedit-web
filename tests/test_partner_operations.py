"""Behavioral tests for TASK-192 deterministic partner operations."""

import pymarc
import pytest

from marcedit_web.lib import partner_operations, transforms


def _record_with_sources() -> pymarc.Record:
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(
        pymarc.Field(
            tag="856",
            indicators=["4", "0"],
            subfields=[pymarc.Subfield("u", "https://one.example")],
        )
    )
    record.add_field(
        pymarc.Field(
            tag="856",
            indicators=["4", "2"],
            subfields=[pymarc.Subfield("u", "https://two.example")],
        )
    )
    return record


def test_copy_fields_with_policy_clones_all_sources_and_reports_counts():
    record = _record_with_sources()

    result = partner_operations.copy_fields_with_policy(
        record,
        source_tag="856",
        destination_tag="956",
        occurrence="all",
        existing_field_action="append",
    )

    assert result == {
        "records_inspected": 1,
        "source_fields_matched": 2,
        "destination_fields_created": 2,
        "existing_fields_replaced": 0,
        "records_skipped": 0,
    }
    assert [field.tag for field in record.fields] == ["856", "856", "956", "956"]
    assert record.get_fields("956")[0].get_subfields("u") == [
        "https://one.example"
    ]


def test_copy_fields_with_policy_can_select_first_source_and_skip_existing():
    record = _record_with_sources()
    record.add_field(
        pymarc.Field(
            tag="956",
            indicators=["4", "0"],
            subfields=[pymarc.Subfield("u", "old")],
        )
    )

    result = partner_operations.copy_fields_with_policy(
        record,
        source_tag="856",
        destination_tag="956",
        occurrence="first",
        existing_field_action="skip",
    )

    assert result["source_fields_matched"] == 1
    assert result["destination_fields_created"] == 0
    assert result["records_skipped"] == 1
    assert [field.get_subfields("u") for field in record.get_fields("956")] == [[
        "old"
    ]]


def test_copy_fields_bound_fails_without_partial_mutation():
    record = _record_with_sources()
    before = [
        (
            field.tag,
            getattr(field, "data", None),
            tuple(field.indicators) if not field.is_control_field() else None,
            tuple((sf.code, sf.value) for sf in field.subfields)
            if not field.is_control_field()
            else None,
        )
        for field in record.fields
    ]

    with pytest.raises(ValueError, match="expansion bound"):
        partner_operations.copy_fields_with_policy(
            record,
            source_tag="856",
            destination_tag="956",
            occurrence="all",
            existing_field_action="append",
            max_fields_per_record=1,
        )

    after = [
        (
            field.tag,
            getattr(field, "data", None),
            tuple(field.indicators) if not field.is_control_field() else None,
            tuple((sf.code, sf.value) for sf in field.subfields)
            if not field.is_control_field()
            else None,
        )
        for field in record.fields
    ]
    assert after == before


def test_build_fields_for_matches_uses_each_source_and_skips_missing_values():
    record = _record_with_sources()
    record.add_field(
        pymarc.Field(
            tag="856",
            indicators=["4", "0"],
            subfields=[pymarc.Subfield("y", "label only")],
        )
    )

    result = partner_operations.build_fields_for_matches(
        record,
        source_tag="856",
        destination_tag="945",
        indicators=[" ", " "],
        subfield_templates=[
            {"code": "u", "parts": [{"type": "source_subfield", "code": "u"}]}
        ],
        missing_source_action="skip_field",
        existing_field_action="append",
    )

    assert result["source_fields_matched"] == 3
    assert result["destination_fields_created"] == 2
    assert [field.get_subfields("u") for field in record.get_fields("945")] == [
        ["https://one.example"],
        ["https://two.example"],
    ]


def test_build_fields_for_matches_resolves_record_control_fields():
    record = _record_with_sources()
    record.add_field(pymarc.Field(tag="003", data="NhCcYBP"))

    result = partner_operations.build_fields_for_matches(
        record,
        source_tag="856",
        destination_tag="945",
        indicators=[" ", " "],
        subfield_templates=[
            {
                "code": "a",
                "parts": [
                    {"type": "source_control_field", "tag": "003"}
                ],
            }
        ],
    )

    assert result["destination_fields_created"] == 2
    assert [field.get_subfields("a") for field in record.get_fields("945")] == [
        ["NhCcYBP"],
        ["NhCcYBP"],
    ]


def test_institution_profile_adds_one_row_per_selected_source():
    record = _record_with_sources()

    result = partner_operations.apply_institution_profile(
        record,
        source_tag="856",
        rows=[
            {
                "destination_tag": "945",
                "indicators": [" ", " "],
                "subfields": [["a", "Smith"], ["u", "{source_subfield:u}"]],
            }
        ],
        occurrence="all",
        max_fields_per_record=10,
    )

    assert result["destination_fields_created"] == 2
    assert [field.get_subfields("a") for field in record.get_fields("945")] == [
        ["Smith"],
        ["Smith"],
    ]


def test_partner_operations_are_reexported_through_transforms():
    assert transforms.copy_fields_with_policy is partner_operations.copy_fields_with_policy
    assert transforms.build_fields_for_matches is partner_operations.build_fields_for_matches
    assert transforms.apply_institution_profile is partner_operations.apply_institution_profile


def test_partner_batch_accounting_accumulates_by_operation_key():
    partner_operations.reset_partner_batch_totals()

    partner_operations.record_partner_result(
        "0", {"destination_fields_created": 3}
    )
    partner_operations.record_partner_result(
        "0", {"destination_fields_created": 2}
    )
    partner_operations.record_partner_result(
        "1", {"destination_fields_created": 4}
    )

    assert partner_operations.get_partner_batch_totals() == {"0": 5, "1": 4}
