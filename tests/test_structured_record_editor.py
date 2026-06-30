"""Tests for cataloger-friendly single-record draft conversion."""

from __future__ import annotations

import pytest
from pymarc import Field, Leader, Record, Subfield

from marcedit_web.lib import structured_record_editor
from marcedit_web.lib.rules import parse_rules_text


@pytest.fixture
def rule_set():
    text = (
        "245\tNR\tTITLE STATEMENT\n"
        "ind1\t01\tTitle added entry\n"
        "ind2\t0-9\tNonfiling characters\n"
        "subfield\tabc\tValid Subfields\n"
        "a\tNR\tTitle\n"
    )
    rules, warnings = parse_rules_text(text)
    assert warnings == []
    return rules


def test_record_to_draft_exposes_control_and_variable_fields(record):
    """Catalogers edit field parts directly, not raw `.mrk` syntax."""
    draft = structured_record_editor.record_to_draft(record)

    assert draft.leader == str(record.leader)
    assert draft.control_fields[0].tag == "001"
    assert draft.control_fields[0].data == "1234567890"

    title = next(field for field in draft.variable_fields if field.tag == "245")
    assert title.ind1 == "1"
    assert title.ind2 == "0"
    assert [(sf.code, sf.value) for sf in title.subfields] == [
        ("a", "Test title."),
    ]


def test_draft_to_record_round_trips_control_fields_and_subfields(record):
    """A no-op structured draft rebuilds equivalent MARC content."""
    draft = structured_record_editor.record_to_draft(record)
    rebuilt = structured_record_editor.draft_to_record(draft)

    assert str(rebuilt.leader) == str(record.leader)
    assert rebuilt["001"].data == "1234567890"
    assert rebuilt["008"].data == "180706s2013    nyu     ob    001 0 eng d"
    title = rebuilt["245"]
    assert title.indicators.first == "1"
    assert title.indicators.second == "0"
    assert [(sf.code, sf.value) for sf in title.subfields] == [
        ("a", "Test title."),
    ]


def test_draft_to_record_applies_cataloger_subfield_edits():
    """Editing subfield rows changes the rebuilt pymarc record."""
    record = Record()
    record.leader = Leader("00000nam a2200000 i 4500")
    record.add_field(Field(tag="001", data="abc"))
    record.add_field(
        Field(
            tag="245",
            indicators=["1", "0"],
            subfields=[Subfield("a", "Old title.")],
        )
    )

    draft = structured_record_editor.record_to_draft(record)
    title = draft.variable_fields[0]
    title.subfields[0].value = "New title."
    title.subfields.append(
        structured_record_editor.SubfieldDraft(code="c", value="Example author.")
    )

    rebuilt = structured_record_editor.draft_to_record(draft)

    assert [(sf.code, sf.value) for sf in rebuilt["245"].subfields] == [
        ("a", "New title."),
        ("c", "Example author."),
    ]


def test_structured_draft_uses_single_record_validation(record, rule_set):
    """Structured edits must save through the same validation as source edits."""
    draft = structured_record_editor.record_to_draft(record)
    title = next(field for field in draft.variable_fields if field.tag == "245")
    title.subfields[0].value = "Structured title."

    result = structured_record_editor.validate_draft(draft, rule_set)

    assert result.can_save
    assert result.record["245"].subfields[0].value == "Structured title."


def test_validate_draft_reports_invalid_field_shape():
    """Half-entered structured rows should show a validation error, not crash."""
    draft = structured_record_editor.RecordDraft(
        leader="00000nam a2200000 i 4500",
        variable_fields=[
            structured_record_editor.VariableFieldDraft(
                tag="",
                ind1="1",
                ind2="0",
                subfields=[
                    structured_record_editor.SubfieldDraft("a", "No tag yet.")
                ],
            )
        ],
    )

    result = structured_record_editor.validate_draft(draft)

    assert result.can_save is False
    assert result.fatal_errors


def test_validate_draft_reports_invalid_leader_without_raising():
    """Typing an incomplete leader should not crash the edit screen."""
    draft = structured_record_editor.RecordDraft(leader="too-short")

    result = structured_record_editor.validate_draft(draft)

    assert result.can_save is False
    assert any("structured draft" in msg for msg in result.fatal_errors)


def test_jump_targets_group_common_cataloging_fields(record):
    """Long records need stable jump links for common cataloging sections."""
    draft = structured_record_editor.record_to_draft(record)

    targets = structured_record_editor.jump_targets(draft)

    assert targets[0] == ("fixed", "Leader / control fields")
    assert ("245", "245 Title") in targets
    assert ("506", "506 Access") in targets
    assert ("655", "655 Genre/Form") in targets
    assert ("856", "856 Links") in targets


def test_preview_text_renders_changed_draft_as_mrk(record):
    """Preview before save should show the exact record that will be saved."""
    draft = structured_record_editor.record_to_draft(record)
    title = next(field for field in draft.variable_fields if field.tag == "245")
    title.subfields[0].value = "Previewed title."

    text = structured_record_editor.preview_mrk(draft)

    assert "=245  10$aPreviewed title." in text
