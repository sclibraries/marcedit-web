"""Structured draft conversion for one-record MARC editing."""

from __future__ import annotations

from dataclasses import dataclass, field

from pymarc import Field, Leader, Record, Subfield

from . import mrk_writer, view_edit
from .rules import RuleSet

_JUMP_LABELS = {
    "020": "ISBN",
    "035": "System numbers",
    "245": "Title",
    "300": "Description",
    "336": "Content / media / carrier",
    "337": "Content / media / carrier",
    "338": "Content / media / carrier",
    "506": "Access",
    "650": "Subjects",
    "655": "Genre/Form",
    "700": "Contributors",
    "710": "Contributors",
    "776": "Related records",
    "830": "Series",
    "852": "Holdings",
    "856": "Links",
    "876": "Item data",
    "877": "Item data",
}


@dataclass
class ControlFieldDraft:
    tag: str
    data: str


@dataclass
class SubfieldDraft:
    code: str
    value: str


@dataclass
class VariableFieldDraft:
    tag: str
    ind1: str = " "
    ind2: str = " "
    subfields: list[SubfieldDraft] = field(default_factory=list)


@dataclass
class RecordDraft:
    leader: str
    control_fields: list[ControlFieldDraft] = field(default_factory=list)
    variable_fields: list[VariableFieldDraft] = field(default_factory=list)


def record_to_draft(record: Record) -> RecordDraft:
    """Convert a pymarc record into editable field/subfield rows."""
    draft = RecordDraft(leader=str(record.leader))
    for marc_field in record.fields:
        if marc_field.is_control_field():
            draft.control_fields.append(
                ControlFieldDraft(
                    tag=marc_field.tag,
                    data=marc_field.data or "",
                )
            )
            continue

        draft.variable_fields.append(
            VariableFieldDraft(
                tag=marc_field.tag,
                ind1=_indicator_text(marc_field.indicators.first),
                ind2=_indicator_text(marc_field.indicators.second),
                subfields=[
                    SubfieldDraft(code=sf.code, value=sf.value)
                    for sf in marc_field.subfields
                ],
            )
        )
    return draft


def draft_to_record(draft: RecordDraft) -> Record:
    """Build a pymarc record from structured field/subfield rows."""
    record = Record()
    record.leader = Leader(draft.leader)

    for control in draft.control_fields:
        record.add_field(Field(tag=control.tag.strip(), data=control.data))

    for variable in draft.variable_fields:
        record.add_field(
            Field(
                tag=variable.tag.strip(),
                indicators=[
                    _indicator_value(variable.ind1),
                    _indicator_value(variable.ind2),
                ],
                subfields=[
                    Subfield(code=sf.code.strip(), value=sf.value)
                    for sf in variable.subfields
                    if sf.code.strip()
                ],
            )
        )

    return record


def validate_draft(
    draft: RecordDraft,
    rule_set: RuleSet | None = None,
) -> view_edit.SingleRecordParseResult:
    """Validate a structured draft through the existing single-record path."""
    try:
        record = draft_to_record(draft)
    except Exception as exc:  # noqa: BLE001 - pymarc raises several shapes
        return view_edit.SingleRecordParseResult(
            fatal_errors=[f"Invalid structured draft: {exc}"]
        )

    text = mrk_writer.render_records_mrk([record])
    return view_edit.parse_and_validate_single_record(text, rule_set)


def preview_mrk(draft: RecordDraft) -> str:
    """Return canonical `.mrk` text for the current structured draft."""
    return mrk_writer.render_records_mrk([draft_to_record(draft)])


def jump_targets(draft: RecordDraft) -> list[tuple[str, str]]:
    """Build stable jump anchors for common sections present in the draft."""
    targets = [("fixed", "Leader / control fields")]
    seen: set[str] = set()
    for field in draft.variable_fields:
        label = _JUMP_LABELS.get(field.tag)
        if label is None or field.tag in seen:
            continue
        seen.add(field.tag)
        targets.append((field.tag, f"{field.tag} {label}"))
    return targets


def _indicator_text(value: str | None) -> str:
    return value or " "


def _indicator_value(value: str) -> str:
    value = value[:1]
    return value if value else " "
