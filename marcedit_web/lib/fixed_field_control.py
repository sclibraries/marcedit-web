"""Structured editing model for LDR, 006, and 007 fixed fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pymarc import Field, Leader, Record


@dataclass(frozen=True)
class FixedPosition:
    """One editable byte or byte range inside a fixed field."""

    id: str
    tag: str
    label: str
    start: int
    length: int
    value: str
    help: str
    allowed: tuple[tuple[str, str], ...] = ()

    @property
    def end(self) -> int:
        return self.start + self.length

    def values(self) -> list[str]:
        return [value for value, _label in self.allowed]


@dataclass(frozen=True)
class _PositionSpec:
    tag: str
    label: str
    start: int
    length: int
    help: str
    allowed: tuple[tuple[str, str], ...] = ()

    @property
    def id(self) -> str:
        return f"{self.tag}_{self.start}"


_FORM_OF_ITEM = (
    (" ", "Not specified / not electronic"),
    ("o", "Online"),
    ("q", "Direct electronic"),
    ("s", "Electronic"),
    ("|", "No attempt to code"),
)

_LDR_SPECS = (
    _PositionSpec(
        "LDR", "Record status", 5, 1, "Leader position 05.",
        (
            ("a", "Increase in encoding level"),
            ("c", "Corrected or revised"),
            ("d", "Deleted"),
            ("n", "New"),
            ("p", "Increase in encoding level from prepublication"),
        ),
    ),
    _PositionSpec(
        "LDR", "Type of record", 6, 1, "Leader position 06.",
        (
            ("a", "Language material"),
            ("c", "Notated music"),
            ("e", "Cartographic material"),
            ("g", "Projected medium"),
            ("i", "Nonmusical sound recording"),
            ("j", "Musical sound recording"),
            ("m", "Computer file"),
            ("o", "Kit"),
            ("p", "Mixed materials"),
            ("r", "Three-dimensional artifact"),
            ("t", "Manuscript language material"),
        ),
    ),
    _PositionSpec(
        "LDR", "Bibliographic level", 7, 1, "Leader position 07.",
        (
            ("a", "Monographic component part"),
            ("b", "Serial component part"),
            ("c", "Collection"),
            ("d", "Subunit"),
            ("i", "Integrating resource"),
            ("m", "Monograph / item"),
            ("s", "Serial"),
        ),
    ),
    _PositionSpec(
        "LDR", "Type of control", 8, 1, "Leader position 08.",
        ((" ", "No specified type"), ("a", "Archival")),
    ),
    _PositionSpec(
        "LDR", "Character coding scheme", 9, 1, "Leader position 09.",
        ((" ", "MARC-8"), ("a", "UCS / Unicode")),
    ),
    _PositionSpec(
        "LDR", "Encoding level", 17, 1, "Leader position 17.",
        (
            (" ", "Full level"),
            ("1", "Full level, material not examined"),
            ("2", "Less-than-full level, material not examined"),
            ("3", "Abbreviated level"),
            ("4", "Core level"),
            ("5", "Partial / preliminary level"),
            ("7", "Minimal level"),
            ("8", "Prepublication level"),
            ("u", "Unknown"),
            ("z", "Not applicable"),
        ),
    ),
    _PositionSpec(
        "LDR", "Descriptive cataloging form", 18, 1, "Leader position 18.",
        (
            (" ", "Non-ISBD"),
            ("a", "AACR2"),
            ("c", "ISBD punctuation omitted"),
            ("i", "ISBD punctuation included"),
            ("u", "Unknown"),
        ),
    ),
    _PositionSpec(
        "LDR", "Multipart resource level", 19, 1, "Leader position 19.",
        (
            (" ", "Not specified / not applicable"),
            ("a", "Set"),
            ("b", "Part with independent title"),
            ("c", "Part with dependent title"),
        ),
    ),
)

_006_SPECS = (
    _PositionSpec(
        "006", "Material type", 0, 1,
        "006 position 00. Determines the meaning of the remaining bytes.",
        (
            ("a", "Language material"),
            ("c", "Notated music"),
            ("d", "Manuscript notated music"),
            ("e", "Cartographic material"),
            ("f", "Manuscript cartographic material"),
            ("g", "Projected medium"),
            ("i", "Nonmusical sound recording"),
            ("j", "Musical sound recording"),
            ("k", "Two-dimensional nonprojectable graphic"),
            ("m", "Computer file / electronic resource"),
            ("o", "Kit"),
            ("p", "Mixed materials"),
            ("r", "Three-dimensional artifact"),
            ("s", "Serial / integrating resource"),
            ("t", "Manuscript language material"),
        ),
    ),
    _PositionSpec(
        "006", "Form of item", 6, 1,
        "006 position 06 for computer-file/e-resource coding.",
        _FORM_OF_ITEM,
    ),
)

_007_SPECS = (
    _PositionSpec(
        "007", "Category of material", 0, 1, "007 position 00.",
        (
            ("a", "Map"),
            ("c", "Electronic resource"),
            ("d", "Globe"),
            ("f", "Tactile material"),
            ("g", "Projected graphic"),
            ("h", "Microform"),
            ("k", "Nonprojected graphic"),
            ("m", "Motion picture"),
            ("o", "Kit"),
            ("q", "Notated music"),
            ("r", "Remote-sensing image"),
            ("s", "Sound recording"),
            ("t", "Text"),
            ("v", "Videorecording"),
            ("z", "Unspecified"),
        ),
    ),
    _PositionSpec(
        "007", "Specific material designation", 1, 1,
        "007 position 01. For electronic resources, 'r' means remote.",
        (
            ("r", "Remote"),
            ("o", "Optical disc"),
            ("z", "Other"),
            ("|", "No attempt to code"),
        ),
    ),
    _PositionSpec(
        "007", "Color", 3, 1, "007 position 03 for electronic resources.",
        (
            ("a", "One color"),
            ("b", "Black-and-white"),
            ("c", "Multicolored"),
            ("g", "Gray scale"),
            ("m", "Mixed"),
            ("n", "Not applicable"),
            ("u", "Unknown"),
            ("z", "Other"),
            ("|", "No attempt to code"),
        ),
    ),
    _PositionSpec(
        "007", "Dimensions", 4, 1,
        "007 position 04 for electronic resources.",
        (
            ("n", "Not applicable"),
            ("u", "Unknown"),
            ("z", "Other"),
            ("|", "No attempt to code"),
        ),
    ),
    _PositionSpec(
        "007", "Sound", 5, 1,
        "007 position 05 for electronic resources.",
        (
            (" ", "No sound / silent"),
            ("a", "Sound"),
            ("u", "Unknown"),
            ("|", "No attempt to code"),
        ),
    ),
)

_SPECS_BY_TAG = {
    "LDR": _LDR_SPECS,
    "006": _006_SPECS,
    "007": _007_SPECS,
}


def parse_fixed_fields(record: Record) -> dict[str, list[FixedPosition]]:
    """Return labeled editable positions for LDR, 006, and 007."""
    return {
        "LDR": _positions_for("LDR", str(record.leader), _LDR_SPECS),
        "006": _positions_for_control_field(record, "006", _006_SPECS),
        "007": _positions_for_control_field(record, "007", _007_SPECS),
    }


def apply_fixed_field_updates(record: Record, updates: dict[str, str]) -> None:
    """Apply fixed-field byte updates after validating every value.

    ``updates`` keys use the stable position ids returned by
    :func:`parse_fixed_fields`, such as ``"LDR_17"`` or ``"006_6"``.
    The record is mutated only after every requested edit validates.
    """
    if not updates:
        return

    parsed_updates = [_parse_update(key, value) for key, value in updates.items()]
    pending: dict[str, list[str]] = {}
    for tag in {tag for tag, _start, _length, _value in parsed_updates}:
        pending[tag] = list(_current_data(record, tag))

    for tag, start, length, value in parsed_updates:
        chars = pending[tag]
        if start + length > len(chars):
            raise ValueError(
                f"{tag} position {start} is outside the current {len(chars)}-byte field"
            )
        chars[start:start + length] = list(value)

    for tag, chars in pending.items():
        data = "".join(chars)
        if tag == "LDR":
            record.leader = Leader(data)
        else:
            field = record.get(tag)
            if field is None:
                raise ValueError(f"{tag} is missing")
            field.data = data


def _positions_for_control_field(
    record: Record,
    tag: str,
    specs: Iterable[_PositionSpec],
) -> list[FixedPosition]:
    field = record.get(tag)
    if field is None:
        return []
    return _positions_for(tag, getattr(field, "data", "") or "", specs)


def _positions_for(
    tag: str,
    data: str,
    specs: Iterable[_PositionSpec],
) -> list[FixedPosition]:
    out: list[FixedPosition] = []
    for spec in specs:
        if spec.start + spec.length > len(data):
            continue
        out.append(FixedPosition(
            id=spec.id,
            tag=tag,
            label=spec.label,
            start=spec.start,
            length=spec.length,
            value=data[spec.start:spec.start + spec.length],
            help=spec.help,
            allowed=spec.allowed,
        ))
    return out


def _parse_update(key: str, value: str) -> tuple[str, int, int, str]:
    try:
        tag, start_text = key.split("_", 1)
        start = int(start_text)
    except ValueError as exc:
        raise ValueError(f"unknown fixed-field position {key!r}") from exc

    specs = _SPECS_BY_TAG.get(tag)
    if specs is None:
        raise ValueError(f"unknown fixed-field tag {tag!r}")
    spec = next((candidate for candidate in specs if candidate.start == start), None)
    if spec is None:
        raise ValueError(f"unknown fixed-field position {key!r}")
    if len(value) != spec.length:
        raise ValueError(
            f"{key} expected {spec.length} character"
            f"{'s' if spec.length != 1 else ''}; got {len(value)}"
        )
    allowed = {code for code, _label in spec.allowed}
    if allowed and value not in allowed:
        raise ValueError(f"{key} value {value!r} is not allowed")
    return tag, start, spec.length, value


def _current_data(record: Record, tag: str) -> str:
    if tag == "LDR":
        data = str(record.leader)
        if len(data) != 24:
            raise ValueError(f"LDR is {len(data)} bytes; expected 24")
        return data

    field: Field | None = record.get(tag)
    if field is None:
        raise ValueError(f"{tag} is missing")
    return getattr(field, "data", "") or ""
