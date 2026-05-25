"""Position-labeled structured editor model for the 008 control field.

The 008 is 40 bytes of position-encoded metadata. Positions 0–17 and
35–39 are shared across all material types; positions 18–34 are
material-specific. This module owns the labeling + allowed-value
schema and gives the UI layer two operations:

* :func:`parse_008` — read the record's 008, pick the material-
  specific schema, return one :class:`Position` per byte range with
  its current value resolved.
* :func:`apply_008` — given a dict of ``{position_id: new_value}``,
  rebuild the 40-byte string and write it back. Length and allowed-
  value violations raise :class:`ValueError` **before** the record
  is mutated.

v1 covers Books (BK) and Continuing Resources (CR), the two most
common material types. Music, Maps, Visual Materials, Computer Files,
and Mixed Materials are out of scope today — add a new
``MATERIAL_SCHEMAS`` entry to extend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pymarc import Field, Record

# Sentinel for "no current 008 / not handled by helper".
NO_008 = "<no-008>"


@dataclass(frozen=True)
class Position:
    """One labeled byte range inside the 008 field.

    * ``id`` — stable identifier the UI uses as a widget key + the
      dict key in :func:`apply_008` updates. Format: ``"008_<start>"``.
    * ``label`` — cataloger-facing name (e.g. "Form of item").
    * ``start`` / ``length`` — 0-based byte position and length.
    * ``allowed`` — list of ``(code, label)`` for an enum; ``None``
      means free-form text constrained to ``length`` chars.
    * ``help`` — one-line cataloger help / MARC position hint.
    """

    id: str
    label: str
    start: int
    length: int
    allowed: Optional[list[tuple[str, str]]]
    help: str

    @property
    def end(self) -> int:
        return self.start + self.length

    def values(self) -> Optional[list[str]]:
        """Return just the codes from ``allowed`` (UI option list)."""
        if self.allowed is None:
            return None
        return [code for code, _label in self.allowed]


# ---------------------------------------------------------------------------
# Material schemas
# ---------------------------------------------------------------------------


_FORM_OF_ITEM = [
    (" ", "None of the following"),
    ("a", "Microfilm"),
    ("b", "Microfiche"),
    ("c", "Microopaque"),
    ("d", "Large print"),
    ("f", "Braille"),
    ("o", "Online"),
    ("q", "Direct electronic"),
    ("r", "Regular print reproduction"),
    ("s", "Electronic"),
    ("|", "No attempt to code"),
]


_GOV_PUB = [
    (" ", "Not a government publication"),
    ("a", "Autonomous or semi-autonomous component"),
    ("c", "Multilocal"),
    ("f", "Federal / national"),
    ("i", "International intergovernmental"),
    ("l", "Local"),
    ("m", "Multistate"),
    ("o", "Government (level undetermined)"),
    ("s", "State, provincial, territorial, dependent"),
    ("u", "Unknown if government publication"),
    ("z", "Other type of government publication"),
    ("|", "No attempt to code"),
]


_CATALOGING_SOURCE = [
    (" ", "National bibliographic agency"),
    ("a", "Other national bibliographic agency"),
    ("c", "Cooperative cataloging program"),
    ("d", "Other (most non-LC catalogers)"),
    ("u", "Unknown"),
    ("|", "No attempt to code"),
]


# Shared head (positions 0–17). Reused by every material schema.
_SHARED_HEAD: list[Position] = [
    Position(
        id="008_0", label="Date entered on file",
        start=0, length=6, allowed=None,
        help="YYMMDD — when the record was created. Auto-set by most cataloging clients.",
    ),
    Position(
        id="008_6", label="Type of date / publication status",
        start=6, length=1,
        allowed=[
            ("b", "No dates given; B.C. date"),
            ("c", "Continuing resource currently published"),
            ("d", "Continuing resource ceased publication"),
            ("e", "Detailed date"),
            ("i", "Inclusive dates of collection"),
            ("k", "Range of years of bulk of collection"),
            ("m", "Multiple dates"),
            ("n", "Dates unknown"),
            ("p", "Date of distribution / release / issue and prod./recording session"),
            ("q", "Questionable date"),
            ("r", "Reprint / reissue date AND original date"),
            ("s", "Single known / probable date"),
            ("t", "Publication date AND copyright date"),
            ("u", "Continuing resource status unknown"),
            ("|", "No attempt to code"),
        ],
        help="Position 06.",
    ),
    Position(
        id="008_7", label="Date 1",
        start=7, length=4, allowed=None,
        help="YYYY (or 'uuuu' for unknown). Positions 07-10.",
    ),
    Position(
        id="008_11", label="Date 2",
        start=11, length=4, allowed=None,
        help="YYYY (or 'uuuu' / '||||'). Positions 11-14.",
    ),
    Position(
        id="008_15", label="Place of publication",
        start=15, length=3, allowed=None,
        help="MARC country code (e.g., 'enk', 'nyu', 'xxu'). Positions 15-17.",
    ),
]


# Shared tail (positions 35–39).
_SHARED_TAIL: list[Position] = [
    Position(
        id="008_35", label="Language",
        start=35, length=3, allowed=None,
        help="3-char MARC language code (e.g., 'eng', 'fre', 'spa'). Positions 35-37.",
    ),
    Position(
        id="008_38", label="Modified record",
        start=38, length=1,
        allowed=[
            (" ", "Not modified"),
            ("d", "Dashed-on information omitted"),
            ("o", "Completely romanized / printed cards"),
            ("r", "Completely romanized / printed cards Latin"),
            ("s", "Shortened"),
            ("x", "Missing characters"),
            ("|", "No attempt to code"),
        ],
        help="Position 38.",
    ),
    Position(
        id="008_39", label="Cataloging source",
        start=39, length=1, allowed=_CATALOGING_SOURCE,
        help="Position 39.",
    ),
]


# Books (BK) — positions 18–34.
_BK_MIDDLE: list[Position] = [
    Position(
        id="008_18", label="Illustrations",
        start=18, length=4, allowed=None,
        help="Up to 4 single-char codes; space-fill unused. Positions 18-21.",
    ),
    Position(
        id="008_22", label="Target audience",
        start=22, length=1,
        allowed=[
            (" ", "Unknown / not specified"),
            ("a", "Preschool"),
            ("b", "Primary"),
            ("c", "Pre-adolescent"),
            ("d", "Adolescent"),
            ("e", "Adult"),
            ("f", "Specialized"),
            ("g", "General"),
            ("j", "Juvenile"),
            ("|", "No attempt to code"),
        ],
        help="Position 22.",
    ),
    Position(
        id="008_23", label="Form of item",
        start=23, length=1, allowed=_FORM_OF_ITEM,
        help="Position 23. 'o' marks online resources.",
    ),
    Position(
        id="008_24", label="Nature of contents",
        start=24, length=4, allowed=None,
        help="Up to 4 single-char codes; space-fill unused. Positions 24-27.",
    ),
    Position(
        id="008_28", label="Government publication",
        start=28, length=1, allowed=_GOV_PUB,
        help="Position 28.",
    ),
    Position(
        id="008_29", label="Conference publication",
        start=29, length=1,
        allowed=[
            ("0", "Not a conference publication"),
            ("1", "Conference publication"),
            ("|", "No attempt to code"),
        ],
        help="Position 29.",
    ),
    Position(
        id="008_30", label="Festschrift",
        start=30, length=1,
        allowed=[
            ("0", "Not a festschrift"),
            ("1", "Festschrift"),
            ("|", "No attempt to code"),
        ],
        help="Position 30.",
    ),
    Position(
        id="008_31", label="Index",
        start=31, length=1,
        allowed=[
            ("0", "No index"),
            ("1", "Index present"),
            ("|", "No attempt to code"),
        ],
        help="Position 31.",
    ),
    Position(
        id="008_32", label="Undefined (32)",
        start=32, length=1, allowed=None,
        help="Position 32 is undefined — leave blank.",
    ),
    Position(
        id="008_33", label="Literary form",
        start=33, length=1,
        allowed=[
            ("0", "Not fiction"),
            ("1", "Fiction"),
            ("c", "Comic strips"),
            ("d", "Dramas"),
            ("e", "Essays"),
            ("f", "Novels"),
            ("h", "Humor / satires / etc."),
            ("i", "Letters"),
            ("j", "Short stories"),
            ("m", "Mixed forms"),
            ("p", "Poetry"),
            ("s", "Speeches"),
            ("u", "Unknown"),
            ("|", "No attempt to code"),
        ],
        help="Position 33.",
    ),
    Position(
        id="008_34", label="Biography",
        start=34, length=1,
        allowed=[
            (" ", "No biographical material"),
            ("a", "Autobiography"),
            ("b", "Individual biography"),
            ("c", "Collective biography"),
            ("d", "Contains biographical information"),
            ("|", "No attempt to code"),
        ],
        help="Position 34.",
    ),
]


# Continuing Resources (CR) — positions 18–34.
_CR_MIDDLE: list[Position] = [
    Position(
        id="008_18", label="Frequency",
        start=18, length=1,
        allowed=[
            (" ", "No determinable frequency"),
            ("a", "Annual"),
            ("b", "Bimonthly"),
            ("c", "Semiweekly"),
            ("d", "Daily"),
            ("e", "Biweekly"),
            ("f", "Semiannual"),
            ("g", "Biennial"),
            ("h", "Triennial"),
            ("i", "Three times a week"),
            ("j", "Three times a month"),
            ("k", "Continuously updated"),
            ("m", "Monthly"),
            ("q", "Quarterly"),
            ("s", "Semimonthly"),
            ("t", "Three times a year"),
            ("u", "Unknown"),
            ("w", "Weekly"),
            ("z", "Other"),
            ("|", "No attempt to code"),
        ],
        help="Position 18.",
    ),
    Position(
        id="008_19", label="Regularity",
        start=19, length=1,
        allowed=[
            ("n", "Normalized irregular"),
            ("r", "Regular"),
            ("u", "Unknown"),
            ("x", "Completely irregular"),
            ("|", "No attempt to code"),
        ],
        help="Position 19.",
    ),
    Position(
        id="008_20", label="Undefined (20)",
        start=20, length=1, allowed=None,
        help="Position 20 is undefined — leave blank.",
    ),
    Position(
        id="008_21", label="Type of continuing resource",
        start=21, length=1,
        allowed=[
            (" ", "None of the following"),
            ("d", "Updating database"),
            ("l", "Updating loose-leaf"),
            ("m", "Monographic series"),
            ("n", "Newspaper"),
            ("p", "Periodical"),
            ("w", "Updating Web site"),
            ("|", "No attempt to code"),
        ],
        help="Position 21.",
    ),
    Position(
        id="008_22", label="Form of original item",
        start=22, length=1, allowed=_FORM_OF_ITEM,
        help="Position 22.",
    ),
    Position(
        id="008_23", label="Form of item",
        start=23, length=1, allowed=_FORM_OF_ITEM,
        help="Position 23. 'o' marks online resources.",
    ),
    Position(
        id="008_24", label="Nature of entire work",
        start=24, length=1, allowed=None,
        help="Single-char code; ' ' = not specified. Position 24.",
    ),
    Position(
        id="008_25", label="Nature of contents",
        start=25, length=3, allowed=None,
        help="Up to 3 single-char codes; space-fill unused. Positions 25-27.",
    ),
    Position(
        id="008_28", label="Government publication",
        start=28, length=1, allowed=_GOV_PUB,
        help="Position 28.",
    ),
    Position(
        id="008_29", label="Conference publication",
        start=29, length=1,
        allowed=[
            ("0", "Not a conference publication"),
            ("1", "Conference publication"),
            ("|", "No attempt to code"),
        ],
        help="Position 29.",
    ),
    Position(
        id="008_30", label="Undefined (30)",
        start=30, length=1, allowed=None,
        help="Position 30 is undefined — leave blank.",
    ),
    Position(
        id="008_31", label="Undefined (31)",
        start=31, length=1, allowed=None,
        help="Position 31 is undefined — leave blank.",
    ),
    Position(
        id="008_32", label="Undefined (32)",
        start=32, length=1, allowed=None,
        help="Position 32 is undefined — leave blank.",
    ),
    Position(
        id="008_33", label="Original alphabet or script",
        start=33, length=1, allowed=None,
        help="Single-char code; ' ' = no alphabet, 'a' = Roman, etc. Position 33.",
    ),
    Position(
        id="008_34", label="Entry convention",
        start=34, length=1,
        allowed=[
            ("0", "Successive entry"),
            ("1", "Latest entry"),
            ("2", "Integrated entry"),
            ("|", "No attempt to code"),
        ],
        help="Position 34.",
    ),
]


# Material code → ordered position list. The list IS the schema —
# parse_008 and apply_008 walk it linearly. The exact concatenation of
# (start, length) MUST cover bytes 0–39 with no gaps or overlaps for
# a schema to be valid.
MATERIAL_SCHEMAS: dict[str, list[Position]] = {
    "BK": _SHARED_HEAD + _BK_MIDDLE + _SHARED_TAIL,
    "CR": _SHARED_HEAD + _CR_MIDDLE + _SHARED_TAIL,
}


# Cataloger-facing label for each material code.
MATERIAL_LABELS: dict[str, str] = {
    "BK": "Books (BK)",
    "CR": "Continuing Resources (CR)",
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def material_type_for(record: Record) -> Optional[str]:
    """Return ``"BK"`` / ``"CR"`` / ``None`` from leader bytes 06 + 07.

    * **BK** — type 06 in ``"at"`` (language material / manuscript
      language material) AND bib level 07 == ``"m"`` (monograph).
      Music (06=c/d/j), maps (e/f), visual materials (g/k/r), and
      mixed/computer/etc. monographs are NOT BK; they have their
      own 008 layouts not covered in v1.
    * **CR** — bib level 07 in ``"si"`` (serial / integrating
      resource), regardless of type 06.

    Anything else returns ``None`` — the helper degrades gracefully
    ("material type not handled — edit via .mrk editor").
    """
    try:
        rtype = record.leader[6]
        blevel = record.leader[7]
    except (IndexError, AttributeError):
        return None
    if blevel in "si":
        return "CR"
    if rtype in "at" and blevel == "m":
        return "BK"
    return None


# ---------------------------------------------------------------------------
# Parse + Apply
# ---------------------------------------------------------------------------


@dataclass
class ParsedPosition:
    """One position with its current resolved value."""

    position: Position
    value: str


def parse_008(record: Record) -> tuple[Optional[str], list[ParsedPosition]]:
    """Return ``(material_code, parsed_positions)``.

    ``material_code`` is ``"BK"`` / ``"CR"`` / ``None``. When None,
    the position list is empty — the UI shows a "material not handled"
    note. When the record has no 008 field, returns
    ``(None, [])`` so the UI can prompt the cataloger to add one.

    Positions are slow-padded to their declared length so a truncated
    008 (rare but seen in the wild) still renders without raising.
    """
    material = material_type_for(record)
    if material is None:
        return None, []
    schema = MATERIAL_SCHEMAS.get(material)
    if not schema:
        return None, []
    field_008 = record.get("008")
    if field_008 is None:
        return material, []
    data = (field_008.data or "").ljust(40)[:40]
    out: list[ParsedPosition] = []
    for pos in schema:
        chunk = data[pos.start:pos.end]
        out.append(ParsedPosition(position=pos, value=chunk))
    return material, out


def apply_008(record: Record, position_values: dict[str, str]) -> None:
    """Recompose the 40-byte 008 from ``position_values`` and write back.

    Raises :class:`ValueError` **before** mutating the record when:

    * The record's material type isn't in :data:`MATERIAL_SCHEMAS`.
    * A position value's length doesn't match its declared
      ``Position.length``.
    * A position is an enum and the supplied value isn't in
      ``Position.values()`` (a literal space is always accepted for
      blank positions even when the enum doesn't list it).
    * The recomposed string isn't exactly 40 bytes.

    Missing positions in ``position_values`` fall back to the current
    bytes in the existing 008 (so a partial-update is safe).
    """
    material = material_type_for(record)
    if material is None or material not in MATERIAL_SCHEMAS:
        raise ValueError(
            "Record material type isn't handled by the 008 helper "
            "(supported: " + ", ".join(MATERIAL_SCHEMAS) + ")"
        )
    schema = MATERIAL_SCHEMAS[material]
    field_008 = record.get("008")
    current = (field_008.data if field_008 else "").ljust(40)[:40]

    pieces: list[str] = []
    for pos in schema:
        existing = current[pos.start:pos.end]
        user_set = pos.id in position_values
        supplied = position_values.get(pos.id, existing)
        if not isinstance(supplied, str):
            raise ValueError(f"{pos.label}: value must be a string")
        if len(supplied) != pos.length:
            raise ValueError(
                f"{pos.label}: expected {pos.length} char(s), got "
                f"{len(supplied)} (value={supplied!r})"
            )
        # Only validate the enum when the user explicitly set this
        # position. Existing-byte fallbacks (a record with a legacy
        # 008 the cataloger didn't touch) can carry codes outside our
        # current allowed-value table; refusing to write those would
        # punish the cataloger for not editing every position.
        if user_set and pos.allowed is not None and supplied not in pos.values():
            raise ValueError(
                f"{pos.label}: {supplied!r} isn't an allowed value "
                f"({', '.join(repr(v) for v in pos.values())})"
            )
        pieces.append(supplied)

    new_data = "".join(pieces)
    if len(new_data) != 40:
        raise ValueError(
            f"Recomposed 008 is {len(new_data)} bytes, not 40 — "
            "schema bug; refusing to write"
        )

    # Validation done — now mutate.
    if field_008 is None:
        record.add_ordered_field(Field(tag="008", data=new_data))
    else:
        field_008.data = new_data
