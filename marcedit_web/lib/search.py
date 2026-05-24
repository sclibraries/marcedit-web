"""Advanced record search.

Supports a small query language for finding records by tag, subfield,
byte position, or plain text. Designed to fit the cataloger workflow:

* ``foo`` — find records where any field contains "foo"
* ``245:foo`` — find records where some 245 field contains "foo"
* ``245$a:foo`` — find records where 245 $a contains "foo"
* ``008/28:i`` — find records where 008 byte position 28 equals "i"
* ``245$a:"exact phrase"`` — quoted phrases match verbatim

Matching is case-insensitive by default. The :func:`matching_records`
generator streams 0-based record indices so the caller can stop early
(useful when displaying paginated results).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

from .record_store import RecordStore


@dataclass(frozen=True)
class SearchQuery:
    """One structured search expression.

    Empty queries (all fields ``None``) match every record. The View
    tab treats this as "search disabled".
    """

    text: Optional[str] = None
    tag: Optional[str] = None              # None = any tag
    subfield: Optional[str] = None         # None = any subfield (variable fields)
    byte_position: Optional[int] = None    # control fields only
    case_sensitive: bool = False

    def is_empty(self) -> bool:
        return not (self.text or self.tag)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_query(s: str) -> SearchQuery:
    """Parse a query string into a :class:`SearchQuery`.

    Malformed inputs fall back to plain-text search (treat the whole
    string as the search text). Never raises.
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
        return SearchQuery(text=_unquote(s))

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
            return SearchQuery(text=_unquote(s))
        tag = tag_part
    elif "$" in prefix:
        tag_part, sub_part = prefix.split("$", 1)
        if len(sub_part) != 1:
            return SearchQuery(text=_unquote(s))
        tag = tag_part
        sub = sub_part.lower()
    else:
        tag = prefix

    if not _valid_tag(tag):
        return SearchQuery(text=_unquote(s))

    return SearchQuery(
        tag=tag,
        subfield=sub,
        byte_position=byte_pos,
        text=_unquote(rest),
    )


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

    needle = query.text or ""
    if not query.case_sensitive:
        needle = needle.lower()

    for idx, record in enumerate(store.iter_records()):
        if _record_matches(record, query, needle):
            yield idx


def _record_matches(record, query: SearchQuery, needle: str) -> bool:
    if query.tag is None:
        return _any_field_contains(record, needle, query.case_sensitive)
    if query.byte_position is not None:
        return _byte_position_matches(
            record, query.tag, query.byte_position, needle, query.case_sensitive
        )
    if query.subfield is not None:
        return _subfield_contains(
            record, query.tag, query.subfield, needle, query.case_sensitive
        )
    return _tag_contains(record, query.tag, needle, query.case_sensitive)


def _norm(value: str, case_sensitive: bool) -> str:
    return value if case_sensitive else value.lower()


def _any_field_contains(record, needle: str, case_sensitive: bool) -> bool:
    # Leader
    leader = str(record.leader) if record.leader else ""
    if needle in _norm(leader, case_sensitive):
        return True
    for f in record.fields:
        # Control field: check data directly.
        data = getattr(f, "data", None)
        if data is not None:
            if needle in _norm(data, case_sensitive):
                return True
            continue
        # Variable field: walk subfields.
        for sf in f.subfields:
            if needle in _norm(sf.value, case_sensitive):
                return True
    return False


def _tag_contains(record, tag: str, needle: str, case_sensitive: bool) -> bool:
    if tag == "LDR":
        leader = str(record.leader) if record.leader else ""
        return needle in _norm(leader, case_sensitive)
    for f in record.get_fields(tag):
        data = getattr(f, "data", None)
        if data is not None:
            if needle in _norm(data, case_sensitive):
                return True
            continue
        for sf in f.subfields:
            if needle in _norm(sf.value, case_sensitive):
                return True
    return False


def _subfield_contains(
    record, tag: str, subfield: str, needle: str, case_sensitive: bool,
) -> bool:
    for f in record.get_fields(tag):
        for sf in f.subfields:
            if sf.code == subfield and needle in _norm(sf.value, case_sensitive):
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
