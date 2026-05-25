"""Format converters for the Marc Tools page.

Four input/output formats, with pymarc owning the underlying
binary ↔ MARCXML conversion. ``.mrk`` round-trips through the
project's own :mod:`mrk_parser` + :mod:`mrk_writer` so the
representation stays consistent with the inline editor's contract
(MarcEdit-style ``$`` subfield delimiter, ``\\`` for blank control
field bytes).

All converters operate on in-memory bytes / strings — the Marc Tools
page hands the result to ``st.download_button``. No streaming;
uploads are bounded by the per-feature quotas in :mod:`quotas`.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Iterator

import pymarc
from pymarc import marcxml

from . import mrk_parser, mrk_writer


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ConversionResult:
    """Outcome of one conversion call.

    ``output`` is the serialized result. ``record_count`` is the
    number of records that parsed cleanly; ``malformed_count`` is the
    number of source records pymarc skipped (truncated, bad
    directory, etc.). ``warnings`` carries cataloger-readable hints
    surfaced in the UI; ``line_errors`` is populated by the
    .mrk-to-binary path so the cataloger can fix specific lines.
    """

    output: bytes | str
    record_count: int = 0
    malformed_count: int = 0
    warnings: list[str] = field(default_factory=list)
    line_errors: list[mrk_parser.LineError] = field(default_factory=list)


# Default columns for CSV preview / export. Each entry is
# ``(column_name, tag, subfield_codes_or_None)``. Control fields
# (00X) read from ``.data``; variable fields concatenate matching
# subfield values with ``" / "``. None for subfield_codes means
# "every subfield value, joined".
DEFAULT_CSV_COLUMNS: list[tuple[str, str, str | None]] = [
    ("001", "001", None),
    ("008_date_1", "008_DATE1", None),  # special: positions 07-10 of 008
    ("100_a", "100", "a"),
    ("245_a", "245", "a"),
    ("245_b", "245", "b"),
    ("260_a", "260", "a"),
    ("260_b", "260", "b"),
    ("260_c", "260", "c"),
    ("020_a", "020", "a"),
    ("022_a", "022", "a"),
    ("856_u", "856", "u"),
]


# ---------------------------------------------------------------------------
# .mrc binary  →  .mrk text
# ---------------------------------------------------------------------------


def to_mrk_text(record_bytes: bytes) -> ConversionResult:
    """Convert a binary MARC blob to MarcEdit-style ``.mrk`` text."""
    records, malformed = _read_binary(record_bytes)
    text = mrk_writer.render_records_mrk(records)
    return ConversionResult(
        output=text,
        record_count=len(records),
        malformed_count=malformed,
    )


# ---------------------------------------------------------------------------
# .mrk text  →  .mrc binary
# ---------------------------------------------------------------------------


def to_binary_from_mrk(text: str) -> ConversionResult:
    """Parse ``.mrk`` text and emit binary MARC bytes.

    Line-pinned parse errors land in :attr:`ConversionResult.line_errors`
    so the page can render them inline. Records that didn't assemble
    into a complete pymarc.Record (fatal `.mrk` violations) increment
    ``malformed_count`` without halting the conversion — surviving
    records still serialize.
    """
    parsed, file_errors = mrk_parser.parse_mrk(text or "")
    records: list[pymarc.Record] = []
    line_errors = list(file_errors)
    malformed = 0
    for pr in parsed:
        line_errors.extend(pr.errors)
        if pr.record is None:
            malformed += 1
            continue
        records.append(pr.record)
    out = _write_binary(records)
    return ConversionResult(
        output=out,
        record_count=len(records),
        malformed_count=malformed,
        line_errors=line_errors,
    )


# ---------------------------------------------------------------------------
# .mrc binary  →  MARCXML
# ---------------------------------------------------------------------------


def to_marcxml(record_bytes: bytes) -> ConversionResult:
    """Convert binary MARC to a MARCXML ``<collection>`` document."""
    records, malformed = _read_binary(record_bytes)
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<collection xmlns="http://www.loc.gov/MARC21/slim">',
    ]
    for r in records:
        # ``record_to_xml`` returns bytes for a single <record> element
        # WITHOUT the XML declaration. Decode + strip whitespace.
        xml_bytes = marcxml.record_to_xml(r, namespace=False)
        parts.append(xml_bytes.decode("utf-8").strip())
    parts.append("</collection>")
    return ConversionResult(
        output="\n".join(parts).encode("utf-8"),
        record_count=len(records),
        malformed_count=malformed,
    )


# ---------------------------------------------------------------------------
# MARCXML  →  .mrc binary
# ---------------------------------------------------------------------------


def to_binary_from_marcxml(xml_text: str | bytes) -> ConversionResult:
    """Parse MARCXML and emit a binary MARC blob.

    Accepts either text or bytes. Malformed XML raises ``ValueError``
    — the page surfaces this as a user-facing error.

    TASK-035 hardening: reject documents that declare a ``<!DOCTYPE``
    or any ``<!ENTITY`` before handing the bytes to pymarc's stdlib
    SAX parser. This blocks billion-laughs entity expansion and XXE
    by refusing to parse the shapes that need them. A full
    ``defusedxml`` boundary would be stricter still; the byte-scan
    is the cheap defense that covers the cataloger workload without
    a new dependency.
    """
    if isinstance(xml_text, str):
        xml_bytes = xml_text.encode("utf-8")
    else:
        xml_bytes = xml_text

    _reject_unsafe_xml(xml_bytes)

    try:
        records = marcxml.parse_xml_to_array(io.BytesIO(xml_bytes))
    except Exception as exc:  # noqa: BLE001 — pymarc raises a mix of types
        raise ValueError(f"could not parse MARCXML: {exc}") from exc
    out = _write_binary(records)
    return ConversionResult(
        output=out,
        record_count=len(records),
        malformed_count=0,
    )


# Full-document scan via ``re`` so we don't materialize a
# lowercase copy (a 2 GB ``.lower()`` would allocate another 2 GB).
# The regex engine handles case folding internally. ``DOTALL`` isn't
# needed — the patterns are pure literals — but ``IGNORECASE`` is
# what makes the check resilient to ``<!DocType`` etc.
_DOCTYPE_RE = re.compile(rb"<!doctype", re.IGNORECASE)
_ENTITY_RE = re.compile(rb"<!entity", re.IGNORECASE)


def _reject_unsafe_xml(xml_bytes: bytes) -> None:
    """Raise ``ValueError`` if ``xml_bytes`` declares a DTD or ENTITY.

    Full-document case-insensitive scan. A hostile file could prepend
    arbitrary XML prolog / comment padding before ``<!DOCTYPE``, so
    a head-only scan would miss it. Scanning the whole input via the
    ``re`` engine costs O(n) bytes scanned with no extra allocation,
    bounded by the per-file upload cap.

    MARCXML emitted by pymarc / OCLC / standard cataloging clients
    never contains these declarations, so this is safe to enforce as
    a hard rule.
    """
    if _DOCTYPE_RE.search(xml_bytes):
        raise ValueError(
            "MARCXML with a <!DOCTYPE declaration is refused — "
            "billion-laughs / XXE attack surface. Strip the DTD "
            "from the source file and retry."
        )
    if _ENTITY_RE.search(xml_bytes):
        raise ValueError(
            "MARCXML with an <!ENTITY declaration is refused — "
            "external/parameter entity attack surface. Strip the "
            "entity declarations from the source file and retry."
        )


# ---------------------------------------------------------------------------
# Records  →  CSV rows
# ---------------------------------------------------------------------------


def records_to_csv_rows(
    record_iter: Iterator[pymarc.Record],
    columns: list[tuple[str, str, str | None]] = None,
) -> list[dict[str, str]]:
    """Flatten records to one dict per record, keyed by column name.

    ``columns`` shape: ``[(column_name, tag, subfield_code_or_None), ...]``.
    Special tag ``"008_DATE1"`` reads positions 07–10 of the 008
    control field. Control field tags (`001`, `003`, etc.) read
    ``.data``; variable fields concatenate matching subfield values
    with ``" / "``. ``None`` for subfield_code joins every subfield
    on the field with `" / "`.
    """
    cols = columns or DEFAULT_CSV_COLUMNS
    rows: list[dict[str, str]] = []
    for record in record_iter:
        row: dict[str, str] = {}
        for col_name, tag, sub in cols:
            row[col_name] = _extract_column(record, tag, sub)
        rows.append(row)
    return rows


def write_csv(rows: list[dict[str, str]], columns: list[str]) -> str:
    """Render rows as a CSV string with the supplied column order."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _extract_column(
    record: pymarc.Record, tag: str, sub: str | None
) -> str:
    """Pull one column's display value from a record."""
    if tag == "008_DATE1":
        field_008 = record.get("008")
        if field_008 is None or len(field_008.data) < 11:
            return ""
        return field_008.data[7:11].strip()
    fields = record.get_fields(tag)
    if not fields:
        return ""
    if tag.startswith("00"):
        # Control field — concatenate data of every matching field
        # (typically only one).
        return " / ".join(f.data for f in fields if getattr(f, "data", None))
    values: list[str] = []
    for f in fields:
        if sub is None:
            values.append(" / ".join(sf.value for sf in f.subfields))
        else:
            values.extend(f.get_subfields(sub))
    return " / ".join(v for v in values if v)


# ---------------------------------------------------------------------------
# Binary helpers
# ---------------------------------------------------------------------------


def _read_binary(record_bytes: bytes) -> tuple[list[pymarc.Record], int]:
    """Read a binary MARC blob; return ``(records, malformed_count)``."""
    if not record_bytes:
        return [], 0
    reader = pymarc.MARCReader(
        io.BytesIO(record_bytes), to_unicode=True, permissive=True,
    )
    records: list[pymarc.Record] = []
    malformed = 0
    for r in reader:
        if r is None:
            malformed += 1
            continue
        records.append(r)
    return records, malformed


def _write_binary(records: list[pymarc.Record]) -> bytes:
    """Serialize records to a single binary MARC blob."""
    buf = io.BytesIO()
    writer = pymarc.MARCWriter(buf)
    for r in records:
        writer.write(r)
    return buf.getvalue()
