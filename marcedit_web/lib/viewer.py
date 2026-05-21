"""MARC record viewer helpers.

Records are rendered as MarcEdit-style `.mrk` text (which is what `str(record)`
produces in pymarc). The Streamlit View page displays the result in a
monospace `<pre>` block so subfield delimiters and indicator columns line up.

This module exposes only the rendering and small parsing helpers. The
file-walking and CLI-print paths from the original marc-processing viewer
have been dropped — Streamlit pages work from records already parsed in
`st.session_state`.
"""

from __future__ import annotations

from pymarc import Record


# --- index / field filtering -------------------------------------------------


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
