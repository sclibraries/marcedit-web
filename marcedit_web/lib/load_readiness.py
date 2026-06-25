"""FOLIO / EDS CC load-readiness warnings.

These checks are intentionally profile-specific. They do not replace generic
MARC validation; they make catalog-loading prerequisites explicit in the
Validate issue table.
"""

from __future__ import annotations

from typing import Iterable

from pymarc import Record

from .errors import Issue, make_record_issue


_EXPECTED_006_LENGTH = 18
_EXPECTED_008_LENGTH = 40
_FORM_OF_ITEM_POS = 23
_RDA_REQUIRED_TAGS = ("336", "337", "338")

# MARC 007 length depends on category of material, encoded in byte 0.
_EXPECTED_007_LENGTHS: dict[str, set[int]] = {
    "a": {8},
    "c": {6, 14},
    "d": {6},
    "f": {10},
    "g": {9},
    "h": {13},
    "k": {6},
    "m": {23},
    "o": {2},
    "q": {2},
    "r": {11},
    "s": {14},
    "t": {2},
    "v": {9},
    "z": {2},
}


def validate_records(records: Iterable[Record]) -> list[Issue]:
    """Return shared FOLIO / EDS CC load-readiness warnings.

    All findings are warnings. They are meant to draw a cataloger's attention
    before a load, not block editing or export.
    """
    issues: list[Issue] = []
    for i, record in enumerate(records, start=1):
        identifier = _identifier(record)
        issues.extend(_validate_006(record, i, identifier))
        issues.extend(_validate_007(record, i, identifier))
        issues.extend(_validate_008(record, i, identifier))
        issues.extend(_validate_rda_carrier_fields(record, i, identifier))
    return issues


def _validate_006(
    record: Record,
    record_index: int,
    identifier: str | None,
) -> list[Issue]:
    fields = record.get_fields("006")
    if not fields:
        return [_issue(
            "load-missing-006",
            "006 is missing",
            "FOLIO / EDS CC load review expects a valid 006 fixed field.",
            record_index,
            identifier,
        )]

    for field in fields:
        data = getattr(field, "data", "") or ""
        if len(data) != _EXPECTED_006_LENGTH:
            return [_issue(
                "load-invalid-006",
                f"006 is {len(data)} bytes; expected {_EXPECTED_006_LENGTH}",
                "Review the 006 fixed field before loading.",
                record_index,
                identifier,
            )]
    return []


def _validate_007(
    record: Record,
    record_index: int,
    identifier: str | None,
) -> list[Issue]:
    fields = record.get_fields("007")
    if not fields:
        return [_issue(
            "load-missing-007",
            "007 is missing",
            "FOLIO / EDS CC load review expects a valid 007 fixed field.",
            record_index,
            identifier,
        )]

    for field in fields:
        data = getattr(field, "data", "") or ""
        category = data[:1]
        expected = _EXPECTED_007_LENGTHS.get(category)
        if expected is None:
            return [_issue(
                "load-invalid-007",
                f"007 category {category!r} is not recognized",
                "Review the 007 category byte before loading.",
                record_index,
                identifier,
            )]
        if len(data) not in expected:
            expected_text = " or ".join(str(value) for value in sorted(expected))
            return [_issue(
                "load-invalid-007",
                f"007 category {category!r} is {len(data)} bytes; expected {expected_text}",
                "Review the 007 fixed field before loading.",
                record_index,
                identifier,
            )]
    return []


def _validate_008(
    record: Record,
    record_index: int,
    identifier: str | None,
) -> list[Issue]:
    field = record.get("008")
    if field is None:
        return [_issue(
            "load-missing-008",
            "008 is missing",
            "FOLIO / EDS CC load review expects a valid 008 fixed field.",
            record_index,
            identifier,
        )]

    data = getattr(field, "data", "") or ""
    if len(data) != _EXPECTED_008_LENGTH:
        return [_issue(
            "load-invalid-008",
            f"008 is {len(data)} bytes; expected {_EXPECTED_008_LENGTH}",
            "Review the 008 fixed field before loading.",
            record_index,
            identifier,
        )]

    actual = data[_FORM_OF_ITEM_POS]
    if actual != "o":
        return [_issue(
            "load-008-form-of-item",
            f"008 byte 23 is {actual!r}; expected 'o' for online",
            "Set 008 position 23 to 'o' before loading online resources.",
            record_index,
            identifier,
        )]
    return []


def _validate_rda_carrier_fields(
    record: Record,
    record_index: int,
    identifier: str | None,
) -> list[Issue]:
    issues: list[Issue] = []
    for tag in _RDA_REQUIRED_TAGS:
        fields = record.get_fields(tag)
        if not fields:
            issues.append(_issue(
                "load-missing-rda-field",
                f"{tag} is missing",
                f"Add {tag} with RDA term and code subfields before loading.",
                record_index,
                identifier,
            ))
            continue
        if not any(_has_nonblank_subfield(field, "a") for field in fields):
            issues.append(_issue(
                "load-missing-rda-a",
                f"{tag} is missing $a",
                f"Add a non-empty {tag} $a term before loading.",
                record_index,
                identifier,
            ))
        if not any(_has_nonblank_subfield(field, "b") for field in fields):
            issues.append(_issue(
                "load-missing-rda-b",
                f"{tag} is missing $b",
                f"Add a non-empty {tag} $b code before loading.",
                record_index,
                identifier,
            ))
    return issues


def _has_nonblank_subfield(field, code: str) -> bool:
    return any((value or "").strip() for value in field.get_subfields(code))


def _issue(
    code: str,
    message: str,
    suggestion: str,
    record_index: int,
    identifier: str | None,
) -> Issue:
    return make_record_issue(
        "warning",
        code,
        message,
        suggestion,
        record_index,
        identifier,
    )


def _identifier(record: Record) -> str | None:
    f001 = record.get("001")
    if f001 is not None and getattr(f001, "data", None):
        return f001.data
    for field in record.get_fields("035"):
        values = field.get_subfields("a")
        if values:
            return values[0]
    return None
