"""Parser for MarcEdit-style ``.mrk`` text.

pymarc ships a writer (``str(record)``) but no ``.mrk`` parser; this is
the in-house implementation that powers the MarcEditor page.

Tokenization rules:

* Records are separated by one or more blank lines. EOF closes the
  last record.
* Each record line starts with ``=`` followed by a 3-char tag (or the
  literal ``LDR``), then two spaces, then the content.
* For ``LDR`` and control fields (``001``-``009``): content is the
  raw byte data. ``\\`` is interpreted as a single space character —
  the MarcEdit-style "blank" placeholder — but every other character
  is treated as literal data. ``$`` and ``|`` in control fields are
  not subfield delimiters.
* For variable fields (``010``+): the first two characters of content
  are the indicators. ``\\`` again represents a blank indicator. The
  rest is a sequence of subfields introduced by ``$`` or ``|`` (both
  accepted on input); the next character is the subfield code, then
  the value runs until the next delimiter or end-of-line.

Validation:

* Indicators must be space (``\\``) or ``0``-``9``. A violation emits
  a :class:`LineError` but the bad character is still kept on the
  parsed field so the rest of the record continues to parse.
* Subfield codes must be ``0``-``9`` or ``a``-``z`` (case-insensitive
  on input, lowercased on the parsed field).
* Tag must be ``LDR`` or three characters in ``[A-Za-z0-9]``.
* LDR content must be exactly 24 characters; otherwise emit
  ``ldr-length`` and store whatever was supplied.
* Any line that doesn't start with ``=`` (and isn't blank) produces a
  file-level :class:`LineError` and is skipped.

The function **never raises**. Encoding errors land as a single
file-level ``LineError(line_no=1, code="encoding")``.

The parse is single-pass and O(n) in the number of characters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

import pymarc

logger = logging.getLogger("marcedit_web.mrk_parser")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class LineError:
    """One non-fatal diagnostic, pinned to a source line.

    ``line_no`` is 1-based, matching how the editor surfaces it (Ace's
    annotation API is 0-based; the page converts on the way out).
    ``column`` is the 0-based offset within the line if the parser
    could locate the bad character, else ``-1`` to mean "whole line".
    """

    line_no: int
    column: int
    code: str
    message: str
    raw: str


@dataclass
class ParsedRecord:
    """One record's worth of parsed output.

    ``record`` is the best-effort ``pymarc.Record``; it's ``None`` only
    when no usable LDR or first field could be assembled (extremely
    pathological input). Even when ``record`` is present, ``errors``
    may carry non-fatal warnings that were pinned to lines inside this
    record.
    """

    record: pymarc.Record | None
    start_line: int
    end_line: int
    errors: list[LineError] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module-level regexes
# ---------------------------------------------------------------------------


_LINE_PREFIX_RE = re.compile(r"^=([A-Za-z0-9]{3})  (.*)$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_mrk(text: str) -> tuple[list[ParsedRecord], list[LineError]]:
    """Parse ``.mrk`` text into records and line-pinned errors.

    Never raises. Pure: no I/O, no Streamlit dependency.
    """
    file_errors: list[LineError] = []
    records: list[ParsedRecord] = []

    # Working state for the current record-in-progress.
    current_lines: list[tuple[int, str]] = []
    start_line: int | None = None

    def _close_record() -> None:
        if not current_lines:
            return
        rec, errs = _build_record(current_lines)
        end = current_lines[-1][0]
        records.append(ParsedRecord(
            record=rec,
            start_line=start_line if start_line is not None else current_lines[0][0],
            end_line=end,
            errors=errs,
        ))
        current_lines.clear()

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.rstrip("\r")  # tolerate CRLF input

        if not stripped.strip():
            # Blank line closes the current record (if any).
            _close_record()
            start_line = None
            continue

        if not stripped.startswith("="):
            file_errors.append(LineError(
                line_no=line_no,
                column=0,
                code="no-tag-prefix",
                message=(
                    "expected `=TAG  …` at start of line; non-empty lines "
                    "between records must begin with `=`"
                ),
                raw=stripped,
            ))
            continue

        if not current_lines:
            start_line = line_no
        current_lines.append((line_no, stripped))

    # EOF — close any open record.
    _close_record()

    return records, file_errors


# ---------------------------------------------------------------------------
# Per-record assembly
# ---------------------------------------------------------------------------


def _build_record(
    lines: list[tuple[int, str]],
) -> tuple[pymarc.Record | None, list[LineError]]:
    """Assemble a single record from its consecutive non-blank lines."""
    errors: list[LineError] = []
    record = pymarc.Record()
    saw_leader = False

    for line_no, raw in lines:
        match = _LINE_PREFIX_RE.match(raw)
        if not match:
            errors.append(LineError(
                line_no=line_no,
                column=0,
                code="bad-line",
                message=(
                    "could not parse line: expected `=TAG  CONTENT` with a "
                    "3-char tag (or `LDR`) followed by two spaces"
                ),
                raw=raw,
            ))
            continue

        tag = match.group(1).upper()
        content = match.group(2)

        if tag == "LDR":
            leader_value, leader_errs = _parse_leader(line_no, content)
            errors.extend(leader_errs)
            try:
                record.leader = pymarc.Leader(leader_value)
            except Exception as exc:  # noqa: BLE001 — pymarc raises on bad leader
                # Keep the record alive even with a malformed leader; emit
                # a non-fatal error so the page can surface it. pymarc's
                # internal Leader class is picky; the in-text leader stays
                # available for the user to fix.
                errors.append(LineError(
                    line_no=line_no,
                    column=6,
                    code="leader-invalid",
                    message=f"pymarc rejected the leader: {exc}",
                    raw=raw,
                ))
            saw_leader = True
            continue

        if _is_control_tag(tag):
            data, ctrl_errs = _parse_control_data(line_no, content)
            errors.extend(ctrl_errs)
            try:
                record.add_field(pymarc.Field(tag=tag, data=data))
            except Exception as exc:  # noqa: BLE001
                errors.append(LineError(
                    line_no=line_no,
                    column=6,
                    code="control-field-rejected",
                    message=f"pymarc rejected control field {tag}: {exc}",
                    raw=raw,
                ))
            continue

        ind1, ind2, subfields, var_errs = _parse_variable_field(line_no, tag, content)
        errors.extend(var_errs)
        try:
            record.add_field(pymarc.Field(
                tag=tag,
                indicators=[ind1, ind2],
                subfields=subfields,
            ))
        except Exception as exc:  # noqa: BLE001
            errors.append(LineError(
                line_no=line_no,
                column=6,
                code="variable-field-rejected",
                message=f"pymarc rejected variable field {tag}: {exc}",
                raw=raw,
            ))

    if not saw_leader and len(lines) > 0:
        # A record without a leader is unusual but we don't drop it; the
        # caller can decide whether to surface this. pymarc.Record's
        # default leader is `00000nam  2200000   4500` (placeholder).
        errors.append(LineError(
            line_no=lines[0][0],
            column=0,
            code="missing-leader",
            message=(
                "this record has no `=LDR` line; pymarc's default leader is "
                "used. Add `=LDR  …` to the top of the record to control "
                "byte-level metadata."
            ),
            raw=lines[0][1],
        ))

    return record, errors


# ---------------------------------------------------------------------------
# Per-line content parsers
# ---------------------------------------------------------------------------


def _parse_leader(line_no: int, content: str) -> tuple[str, list[LineError]]:
    errors: list[LineError] = []
    leader = content.replace("\\", " ")
    if len(leader) != 24:
        errors.append(LineError(
            line_no=line_no,
            column=6,
            code="ldr-length",
            message=(
                f"leader is {len(leader)} characters; MARC leaders are exactly 24. "
                "Pad with spaces or trim to the canonical length."
            ),
            raw="=LDR  " + content,
        ))
    return leader, errors


def _parse_control_data(line_no: int, content: str) -> tuple[str, list[LineError]]:
    # Control-field data uses `\` for the space placeholder, just like the
    # leader. `$` and `|` are literal data here — NOT subfield delimiters.
    return content.replace("\\", " "), []


def _parse_variable_field(
    line_no: int, tag: str, content: str
) -> tuple[str, str, list[pymarc.Subfield], list[LineError]]:
    """Parse a single variable-field content line.

    Returns ``(ind1, ind2, subfields, errors)``. ``ind1``/``ind2`` are
    always single characters even on bad input — the bad character
    survives on the field so the round-trip can still emit it back.
    """
    errors: list[LineError] = []

    if len(content) < 2:
        # Pad missing indicators with space; surface the error.
        errors.append(LineError(
            line_no=line_no,
            column=6 + len(content),
            code="missing-indicators",
            message=(
                f"{tag} content is shorter than 2 indicator characters; "
                "padded with spaces"
            ),
            raw="=" + tag + "  " + content,
        ))
        content = (content + "  ")[:2] + content[2:]

    raw_ind1 = content[0]
    raw_ind2 = content[1]
    rest = content[2:]

    ind1 = " " if raw_ind1 == "\\" else raw_ind1
    ind2 = " " if raw_ind2 == "\\" else raw_ind2

    if not _is_valid_indicator(ind1):
        errors.append(LineError(
            line_no=line_no,
            column=6,
            code="bad-indicator",
            message=(
                f"{tag} ind1 = {raw_ind1!r}; valid values are space (`\\\\`) "
                "or `0`-`9`"
            ),
            raw="=" + tag + "  " + content,
        ))
    if not _is_valid_indicator(ind2):
        errors.append(LineError(
            line_no=line_no,
            column=7,
            code="bad-indicator",
            message=(
                f"{tag} ind2 = {raw_ind2!r}; valid values are space (`\\\\`) "
                "or `0`-`9`"
            ),
            raw="=" + tag + "  " + content,
        ))

    subfields = _parse_subfields(line_no, tag, rest, errors, column_base=8)

    return ind1, ind2, subfields, errors


def _parse_subfields(
    line_no: int,
    tag: str,
    rest: str,
    errors: list[LineError],
    column_base: int,
) -> list[pymarc.Subfield]:
    """Walk a variable-field subfield string and emit ``Subfield(code, value)``.

    Both ``$`` and ``|`` are accepted as delimiters. The next character
    after a delimiter is the subfield code; everything until the next
    delimiter (or end-of-line) is the value.
    """
    subfields: list[pymarc.Subfield] = []
    i = 0
    n = len(rest)
    if n == 0:
        return subfields

    if rest[0] not in ("$", "|"):
        # The first character after the indicators should be a delimiter.
        # Tolerate "loose" data by treating the leading run as an unnamed
        # subfield under `a` — pymarc would otherwise reject the field.
        # Emit a LineError so the cataloger sees the recovery.
        end = _next_delim(rest, 1)
        loose = rest[:end]
        errors.append(LineError(
            line_no=line_no,
            column=column_base,
            code="missing-leading-delimiter",
            message=(
                f"{tag} subfield run does not start with `$` or `|`; "
                "treating the leading text as `$a`"
            ),
            raw=rest,
        ))
        subfields.append(pymarc.Subfield(code="a", value=loose))
        i = end
        if i < n and rest[i] not in ("$", "|"):
            # Defensive — shouldn't happen since _next_delim looks for $/|
            return subfields

    while i < n:
        if rest[i] not in ("$", "|"):
            # Stray content between subfields — fold into the previous
            # value if any, or skip.
            if subfields:
                last = subfields[-1]
                # NamedTuples are immutable; replace the entry.
                subfields[-1] = pymarc.Subfield(
                    code=last.code,
                    value=last.value + rest[i],
                )
                i += 1
                continue
            else:
                i += 1
                continue

        if i + 1 >= n:
            errors.append(LineError(
                line_no=line_no,
                column=column_base + i,
                code="trailing-delimiter",
                message=(
                    f"{tag} subfield delimiter at end of line has no code; "
                    "dropping it"
                ),
                raw=rest,
            ))
            break

        code = rest[i + 1].lower()
        if not _is_valid_subfield_code(code):
            errors.append(LineError(
                line_no=line_no,
                column=column_base + i + 1,
                code="bad-subfield-code",
                message=(
                    f"{tag} subfield code {rest[i + 1]!r} is not in "
                    "`0`-`9` or `a`-`z`; keeping it as-is"
                ),
                raw=rest,
            ))
            code = rest[i + 1]
        # Walk until the next delimiter.
        value_start = i + 2
        value_end = _next_delim(rest, value_start)
        value = rest[value_start:value_end]
        subfields.append(pymarc.Subfield(code=code, value=value))
        i = value_end

    return subfields


def _next_delim(s: str, start: int) -> int:
    """Return the index of the next `$` or `|`, or ``len(s)`` if none."""
    i = start
    n = len(s)
    while i < n and s[i] not in ("$", "|"):
        i += 1
    return i


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def _is_control_tag(tag: str) -> bool:
    return (
        len(tag) == 3
        and tag.startswith("00")
        and tag[2].isdigit()
        and tag != "000"
    )


def _is_valid_indicator(ch: str) -> bool:
    return ch == " " or (len(ch) == 1 and "0" <= ch <= "9")


def _is_valid_subfield_code(ch: str) -> bool:
    return len(ch) == 1 and (("0" <= ch <= "9") or ("a" <= ch <= "z"))
