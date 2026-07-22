"""MARC record viewer helpers.

Two record-rendering shapes live here:

* :func:`render_record_human` walks the raw MARC bytes for **display**.
  Spaces stay spaces, pipes stay pipes (they're real MARC fill chars,
  not encoding artifacts), and the subfield delimiter byte 0x1F is
  rendered as ``‡`` so it's visually distinct from `$` or `|`
  characters that legitimately appear in field values. This is what
  the Streamlit View page shows.

* :func:`render_record` produces MarcEdit-style ``.mrk`` text via
  ``str(record)`` — the round-trippable shape the inline editor and
  the ``.mrk`` parser exchange. Spaces in control fields render as
  ``\\`` per MarcEdit convention. Kept for the Ace editor pre-fill
  path and any test that pins the .mrk shape.

The Streamlit page displays each result in a monospace ``<pre>``
block so subfield delimiters and indicator columns line up.
"""

from __future__ import annotations

from pymarc import Record

from . import marc_diff


# MARC subfield delimiter byte. Rendered as the double-dagger glyph in
# the human-readable view because it's visually unambiguous against
# subfield values that may legitimately contain ``$`` or ``|``.
_SUBFIELD_DELIM = "\x1f"
_SUBFIELD_DISPLAY = "‡"


# --- index / field filtering -------------------------------------------------


def field_order_inversions(
    record: Record, *, limit: int = 20,
) -> list[tuple[str, str]]:
    """Return bounded adjacent descending tags without changing the record."""
    if limit <= 0:
        return []
    inversions: list[tuple[str, str]] = []
    for previous, current in zip(record.fields, record.fields[1:]):
        if current.tag < previous.tag:
            inversions.append((previous.tag, current.tag))
            if len(inversions) >= limit:
                break
    return inversions


def parse_indices(spec: str) -> set[int]:
    """Parse "1", "1-3", "1,3,5", "1-3,7" into a set of 1-based ints.

    Raises ValueError for malformed input.
    """
    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(chunk))
    if not out:
        raise ValueError(f"no indices parsed from {spec!r}")
    return out


def parse_fields(spec: str) -> set[str]:
    """Parse "856", "035,856", "035 856" into a set of 3-char tags."""
    tags: set[str] = set()
    for chunk in spec.replace(",", " ").split():
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) != 3 or not all(c.isalnum() for c in chunk):
            raise ValueError(f"not a MARC tag: {chunk!r}")
        tags.add(chunk)
    return tags


# --- .mrk rendering ----------------------------------------------------------


def render_record(record: Record, *, fields: set[str] | None = None) -> str:
    """Return the .mrk text for `record`, optionally filtered to `fields`.

    `fields` includes the leader/control fields if "LDR", "001", "008" etc.
    are passed; pass None for everything.
    """
    if fields is None:
        return str(record)

    out: list[str] = []
    # Leader has tag "LDR" in .mrk output.
    if "LDR" in fields:
        out.append(f"=LDR  {record.leader}")
    for f in record.fields:
        if f.tag in fields:
            out.append(str(f))
    return "\n".join(out)


def render_record_human(
    record: Record, *, fields: set[str] | None = None
) -> str:
    """Return a human-readable rendering of ``record`` for display.

    Walks the raw MARC bytes (via :func:`Record.as_marc`) so the output
    reflects the actual MARC content rather than MarcEdit's
    ``.mrk`` escape conventions. Concretely:

    * Spaces in control fields (008 / 006 / 007 etc.) render as actual
      spaces — no ``\\`` substitution. Catalogers can count byte
      positions directly.
    * Pipe characters (``|``) are MARC fill chars and render as
      themselves.
    * The MARC subfield-delimiter byte (0x1F) renders as ``‡`` so it
      stays visible in a monospace block and never collides with a
      ``$`` or ``|`` that appears legitimately in subfield values.

    ``fields`` filters by 3-char tag (or ``"LDR"`` for the leader),
    same contract as :func:`render_record`.
    """
    raw = record.as_marc()
    lines: list[str] = []
    leader_text = raw[:marc_diff.LEADER_LEN].decode("utf-8", errors="replace")
    if fields is None or "LDR" in fields:
        lines.append(f"=LDR  {leader_text}")
    for tag_bytes, length, start in marc_diff._iter_directory(raw):
        tag = tag_bytes.decode("utf-8", errors="replace")
        if fields is not None and tag not in fields:
            continue
        data = marc_diff._field_bytes(raw, length, start).decode(
            "utf-8", errors="replace"
        ).replace(_SUBFIELD_DELIM, _SUBFIELD_DISPLAY)
        lines.append(f"={tag}  {data}")
    return "\n".join(lines)


def record_title(record: Record) -> str:
    """Best-effort 245 $a, stripped of trailing punctuation. Empty string if missing."""
    f = record.get("245")
    if f is None:
        return ""
    values = f.get_subfields("a")
    return (values[0] if values else "").rstrip(" /:;,.").strip()


def record_identifier(record: Record) -> str:
    """Best-effort identifier: 001, falling back to first 035 $a, or "-" if missing."""
    f = record.get("001")
    if f is not None:
        return f.data
    f035 = record.get("035")
    if f035 is not None:
        vals = f035.get_subfields("a")
        if vals:
            return vals[0]
    return "-"
