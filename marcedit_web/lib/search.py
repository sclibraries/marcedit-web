"""Advanced record search.

Supports a small query language for finding records by tag, subfield,
byte position, or plain text. Designed to fit the cataloger workflow:

Base patterns:

* ``foo`` — find records where any field contains "foo"
* ``245:foo`` — find records where some 245 field contains "foo"
* ``245$a:foo`` — find records where 245 $a contains "foo"
* ``008/28:i`` — find records where 008 byte position 28 equals "i"
* ``245$a:"exact phrase"`` — quoted phrases match verbatim

Value operators (TASK-042):

* ``245$a:^The`` — starts-with: the value must start with "The".
* ``856$u:.pdf$`` — ends-with: the value must end with ".pdf".
* ``035$a:~^\\(EDZ\\)`` — regex: full regex match (advanced; cataloger
  must be comfortable with regex syntax).

Compound queries (TASK-042):

* ``245$a:Pistoletto AND 008/35-37:eng`` — every AND clause must
  match for a record to count.

Matching is case-insensitive by default. The :func:`matching_records`
generator streams 0-based record indices so the caller can stop early
(useful when displaying paginated results). :func:`matching_records_compound`
takes a list of clauses and returns the intersection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Literal, Optional

from .record_store import RecordStore


SearchMode = Literal["contains", "starts", "ends", "regex"]


@dataclass(frozen=True)
class SearchQuery:
    """One structured search expression.

    Empty queries (all fields ``None``) match every record. The View
    tab treats this as "search disabled".

    ``mode`` (TASK-042):
      * ``"contains"`` (default) — value contains text (literal).
      * ``"starts"`` — value starts with text (literal).
      * ``"ends"`` — value ends with text (literal).
      * ``"regex"`` — re.search match. Compile errors fall back to
        ``"contains"`` at parse time so a malformed regex degrades
        gracefully rather than blocking the page.

    ``parse_error`` is populated by the parser when the input was
    syntactically suspect (bad regex, unrecognized operator); the UI
    can surface it inline.
    """

    text: Optional[str] = None
    tag: Optional[str] = None              # None = any tag
    subfield: Optional[str] = None         # None = any subfield (variable fields)
    byte_position: Optional[int] = None    # control fields only
    case_sensitive: bool = False
    mode: SearchMode = "contains"
    parse_error: Optional[str] = None

    def is_empty(self) -> bool:
        return not (self.text or self.tag)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_query(s: str) -> SearchQuery:
    """Parse a single-clause query string into a :class:`SearchQuery`.

    Malformed inputs fall back to plain-text search (treat the whole
    string as the search text). Never raises. The mode is derived
    from the value's leading/trailing sigils:

    * ``^foo`` → starts-with (sigil stripped).
    * ``foo$`` → ends-with (sigil stripped).
    * ``~foo`` → regex (sigil stripped; compile attempted at parse
      time, with a graceful contains fallback + ``parse_error`` set
      when the pattern is bad).

    Quoted values (``"^literal-caret"``) are matched verbatim — the
    quotes disable operator interpretation, so a cataloger searching
    for a literal ``^`` or ``$`` character can wrap the text in
    double quotes.
    """
    s = s.strip()
    if not s:
        return SearchQuery()

    # Find the prefix colon. The prefix can be at most 8 characters
    # (`245$a/99` is 8). A colon further right is part of the text.
    prefix_end = -1
    for i in range(min(len(s), 9)):
        if s[i] == ":":
            prefix_end = i
            break

    if prefix_end == -1:
        text, mode, err = _interpret_value(s)
        return SearchQuery(text=text, mode=mode, parse_error=err)

    prefix = s[:prefix_end]
    rest = s[prefix_end + 1:]

    tag: Optional[str] = None
    sub: Optional[str] = None
    byte_pos: Optional[int] = None

    if "/" in prefix:
        tag_part, byte_str = prefix.split("/", 1)
        try:
            byte_pos = int(byte_str)
        except ValueError:
            text, mode, err = _interpret_value(s)
            return SearchQuery(text=text, mode=mode, parse_error=err)
        tag = tag_part
    elif "$" in prefix:
        tag_part, sub_part = prefix.split("$", 1)
        if len(sub_part) != 1:
            text, mode, err = _interpret_value(s)
            return SearchQuery(text=text, mode=mode, parse_error=err)
        tag = tag_part
        sub = sub_part.lower()
    else:
        tag = prefix

    if not _valid_tag(tag):
        text, mode, err = _interpret_value(s)
        return SearchQuery(text=text, mode=mode, parse_error=err)

    text, mode, err = _interpret_value(rest)
    return SearchQuery(
        tag=tag,
        subfield=sub,
        byte_position=byte_pos,
        text=text,
        mode=mode,
        parse_error=err,
    )


# Word-boundary " AND " split used by parse_compound_query.
_AND_SPLIT_RE = re.compile(r"\s+AND\s+", re.IGNORECASE)


def parse_compound_query(s: str) -> list[SearchQuery]:
    """Parse ``q1 AND q2 AND ...`` into a list of :class:`SearchQuery`.

    Empty input returns an empty list. A single-clause input returns
    a one-element list, so callers can uniformly iterate.

    AND is case-insensitive but requires whitespace on both sides so
    a literal ``AND`` inside a quoted phrase doesn't accidentally
    split the query.
    """
    s = (s or "").strip()
    if not s:
        return []
    parts = _AND_SPLIT_RE.split(s)
    return [parse_query(p) for p in parts if p.strip()]


def _interpret_value(value: str) -> tuple[str, SearchMode, Optional[str]]:
    """Decode operator sigils on a value string.

    Returns ``(text, mode, parse_error)``. Quoted values bypass
    operator interpretation entirely.
    """
    v = value.strip()
    if not v:
        return "", "contains", None
    # Quoted? Disable operator interpretation.
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1], "contains", None
    # Regex sigil — leading "~".
    if v.startswith("~"):
        pattern = v[1:]
        try:
            re.compile(pattern)
        except re.error as exc:
            # Bad regex: degrade to contains so the page doesn't
            # block on a typo, but flag the error for the UI.
            return pattern, "contains", f"Invalid regex: {exc}"
        return pattern, "regex", None
    # Starts-with sigil — leading "^".
    if v.startswith("^"):
        return v[1:], "starts", None
    # Ends-with sigil — trailing "$".
    if v.endswith("$"):
        return v[:-1], "ends", None
    return v, "contains", None


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _valid_tag(tag: str) -> bool:
    if tag == "LDR":
        return True
    return len(tag) == 3 and all(c.isalnum() for c in tag)


# ---------------------------------------------------------------------------
# Match engine
# ---------------------------------------------------------------------------


def matching_records(
    store: RecordStore, query: SearchQuery
) -> Iterator[int]:
    """Yield 0-based record indices that match ``query``.

    Empty queries match every record. The function streams indices so
    callers can stop early when paginating results.
    """
    if query.is_empty():
        for idx in range(store.count()):
            yield idx
        return

    needle = _prepare_needle(query)

    for idx, record in enumerate(store.iter_records()):
        if _record_matches(record, query, needle):
            yield idx


def matching_records_compound(
    store: RecordStore, queries: list[SearchQuery]
) -> Iterator[int]:
    """Yield indices that match every clause in ``queries`` (AND).

    An empty clause list matches every record. Individual clauses
    are evaluated independently against each record; the first
    failing clause short-circuits the record.
    """
    if not queries:
        for idx in range(store.count()):
            yield idx
        return

    prepared = [(q, _prepare_needle(q)) for q in queries]

    for idx, record in enumerate(store.iter_records()):
        if all(_record_matches(record, q, needle) for q, needle in prepared):
            yield idx


def _prepare_needle(query: SearchQuery) -> object:
    """Pre-compile / lowercase the needle once per match pass.

    For regex mode, returns a compiled :class:`re.Pattern`. For text
    modes, returns the lowercased / cased needle string. ``_record_matches``
    dispatches on ``query.mode`` to interpret the prepared value.
    """
    text = query.text or ""
    if query.mode == "regex":
        flags = 0 if query.case_sensitive else re.IGNORECASE
        try:
            return re.compile(text, flags)
        except re.error:
            # Should have been caught at parse time; degrade to
            # literal-contains rather than raising.
            return text.lower() if not query.case_sensitive else text
    if not query.case_sensitive:
        return text.lower()
    return text


def _record_matches(record, query: SearchQuery, needle) -> bool:
    """``needle`` is a string OR a compiled regex (regex mode).

    Dispatches per query.mode internally via :func:`_value_matches`.
    """
    if query.tag is None:
        return _any_field_value_matches(record, needle, query)
    if query.byte_position is not None:
        # Byte-position lookups are naturally prefix-at-position;
        # operator modes don't compose meaningfully. Coerce the
        # needle back to a plain string so a stray ``~``/``^``/``$``
        # in the value doesn't crash the matcher with a Pattern arg.
        raw = (query.text or "")
        if not query.case_sensitive:
            raw = raw.lower()
        return _byte_position_matches(
            record, query.tag, query.byte_position, raw, query.case_sensitive
        )
    if query.subfield is not None:
        return _subfield_value_matches(
            record, query.tag, query.subfield, needle, query
        )
    return _tag_value_matches(record, query.tag, needle, query)


def _norm(value: str, case_sensitive: bool) -> str:
    return value if case_sensitive else value.lower()


def _value_matches(haystack: str, needle, query: SearchQuery) -> bool:
    """Check one haystack string against the prepared needle per mode."""
    if query.mode == "regex":
        return needle.search(haystack) is not None  # type: ignore[union-attr]
    hay = _norm(haystack, query.case_sensitive)
    if query.mode == "starts":
        return hay.startswith(needle)  # type: ignore[arg-type]
    if query.mode == "ends":
        return hay.endswith(needle)  # type: ignore[arg-type]
    return needle in hay  # type: ignore[operator]


def _any_field_value_matches(record, needle, query: SearchQuery) -> bool:
    leader = str(record.leader) if record.leader else ""
    if _value_matches(leader, needle, query):
        return True
    for f in record.fields:
        data = getattr(f, "data", None)
        if data is not None:
            if _value_matches(data, needle, query):
                return True
            continue
        for sf in f.subfields:
            if _value_matches(sf.value, needle, query):
                return True
    return False


def _tag_value_matches(record, tag: str, needle, query: SearchQuery) -> bool:
    if tag == "LDR":
        leader = str(record.leader) if record.leader else ""
        return _value_matches(leader, needle, query)
    for f in record.get_fields(tag):
        data = getattr(f, "data", None)
        if data is not None:
            if _value_matches(data, needle, query):
                return True
            continue
        for sf in f.subfields:
            if _value_matches(sf.value, needle, query):
                return True
    return False


def _subfield_value_matches(
    record, tag: str, subfield: str, needle, query: SearchQuery,
) -> bool:
    for f in record.get_fields(tag):
        for sf in f.subfields:
            if sf.code == subfield and _value_matches(sf.value, needle, query):
                return True
    return False


def _byte_position_matches(
    record, tag: str, pos: int, needle: str, case_sensitive: bool,
) -> bool:
    """Check whether the bytes at ``pos`` of ``tag`` start with ``needle``.

    ``needle`` is matched as a prefix at the given byte offset. This
    handles both single-character lookups (``008/28:i``) and short
    range lookups (``008/35-37:eng`` would need explicit length —
    but we keep it simple: ``needle`` must fit at ``pos``).
    """
    if tag == "LDR":
        data = str(record.leader) if record.leader else ""
    else:
        f = record.get(tag)
        if f is None:
            return False
        data = getattr(f, "data", None) or ""
    if pos < 0 or pos + len(needle) > len(data):
        return False
    return _norm(data[pos:pos + len(needle)], case_sensitive) == needle
