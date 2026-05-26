"""Keeper-selection strategies for the Dedupe page (TASK-043).

When a duplicate group has multiple records, the cataloger needs to
choose *one* to keep — the others go into the deletes export. The
v1 Dedupe page hard-coded "first occurrence" as the keeper; for
real workloads with 4K+ groups, that loses cataloging signal:

* A second indexing of the same record may carry extra vendor IDs
  in 035s (EDZ + SCSK + OCoLC + …) that the first record doesn't.
* The richer record is the better keeper.

This module ships four strategies plus the per-group manual override
hook. Each strategy is a pure function over ``(group_offsets,
source_bytes, **params) → offset``. The render layer wires them up
to the UI; tests live in :mod:`tests.test_dedupe_strategy`.

Strategies:

* ``FIRST_OCCURRENCE`` — current default; tie-break "the one we
  saw first" matches ``marc_diff.index_buffer`` semantics.
* ``MOST_FIELDS`` — count of total fields in each record; pick max.
  Ties → first.
* ``MOST_OF_TAG`` — count of occurrences of ``tag`` in each record;
  pick max. Directly addresses "keep the record with both EDZ and
  SCSK 035s" — set tag=035 and the record with both occurrences
  wins.
* ``FIELD_MATCHES_REGEX`` — first record whose ``tag$subfield``
  contains a regex match. Falls back to first-occurrence when no
  member matches. Useful for "keep the record where 035$a starts
  with SCSK" type rules.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Optional

import pymarc


class KeeperStrategy(enum.Enum):
    """Identifier for the keeper-selection algorithms."""

    FIRST_OCCURRENCE = "first"
    MOST_FIELDS = "most_fields"
    MOST_OF_TAG = "most_of_tag"
    FIELD_MATCHES_REGEX = "field_matches_regex"


@dataclass(frozen=True)
class StrategyParams:
    """Inputs to a strategy beyond the group itself.

    Not every strategy needs every param. ``pick_keeper`` ignores
    fields that don't apply to the chosen strategy.
    """

    tag: Optional[str] = None
    subfield: Optional[str] = None
    pattern: Optional[str] = None
    case_sensitive: bool = False


def _record_at(source_bytes: bytes, offset: int) -> Optional[pymarc.Record]:
    """Slice + parse one record from a buffer at the given byte offset.

    Returns None when the bytes at ``offset`` don't form a parseable
    MARC record — the caller treats that as a tie-break demotion.
    """
    if offset < 0 or offset + 5 > len(source_bytes):
        return None
    try:
        length = int(source_bytes[offset:offset + 5])
    except (ValueError, IndexError):
        return None
    if offset + length > len(source_bytes):
        return None
    chunk = source_bytes[offset:offset + length]
    try:
        return pymarc.Record(data=bytes(chunk))
    except Exception:  # noqa: BLE001 — pymarc raises many shapes
        return None


def validate_params(
    strategy: KeeperStrategy, params: StrategyParams,
) -> Optional[str]:
    """Validate strategy params before applying. Returns error or ``None``.

    TASK-044: ``FIELD_MATCHES_REGEX`` previously fell back to
    first-occurrence silently on a bad pattern — the cataloger saw
    "applied to N groups" but no records actually matched. Surfacing
    the compile error here lets the UI block Apply on invalid input.
    """
    if strategy == KeeperStrategy.MOST_OF_TAG:
        if not params.tag:
            return "Pick a tag (e.g. 035) to count occurrences of."
        return None
    if strategy == KeeperStrategy.FIELD_MATCHES_REGEX:
        if not params.tag:
            return "Pick a tag (e.g. 035) to search within."
        if not params.pattern:
            return "Enter a regex pattern."
        flags = 0 if params.case_sensitive else re.IGNORECASE
        try:
            re.compile(params.pattern, flags)
        except re.error as exc:
            return (
                f"Invalid regex: {exc}. "
                "Note: `(` and `)` are regex group operators; escape "
                "them as `\\(` and `\\)` to match literal parentheses "
                "in the data (e.g. `^\\(SCSK` for values like "
                "`(SCSK2013)...`)."
            )
    return None


def pick_keeper(
    group_offsets: list[int],
    source_bytes: bytes,
    strategy: KeeperStrategy,
    params: StrategyParams = StrategyParams(),
) -> tuple[int, bool]:
    """Pick the keeper offset for one duplicate group.

    Returns ``(offset, matched_strategy)``. ``matched_strategy`` is
    True when the strategy's criterion actually selected a record;
    False when the helper fell back to first-occurrence (no member
    matched the regex; no tag supplied; etc.). The caller uses the
    flag to report "X of N groups actually matched the strategy" in
    the UI.

    Always returns one of ``group_offsets``. Empty group raises
    ``ValueError`` — the caller should never present empty groups.
    """
    if not group_offsets:
        raise ValueError("pick_keeper called with empty group_offsets")

    if strategy == KeeperStrategy.FIRST_OCCURRENCE:
        # The strategy IS first-occurrence, so the match is intentional.
        return group_offsets[0], True

    if strategy == KeeperStrategy.MOST_FIELDS:
        offset, _score = _max_by_with_score(
            group_offsets, source_bytes, _field_count,
        )
        # MOST_FIELDS always selects per its criterion (the highest
        # score wins, even when ties land on the first member).
        return offset, True

    if strategy == KeeperStrategy.MOST_OF_TAG:
        tag = params.tag
        if not tag:
            return group_offsets[0], False
        offset, _score = _max_by_with_score(
            group_offsets, source_bytes,
            lambda r: _count_tag(r, tag),
        )
        return offset, True

    if strategy == KeeperStrategy.FIELD_MATCHES_REGEX:
        return _first_matching(group_offsets, source_bytes, params)

    # Unknown strategy: be defensive, return first occurrence.
    return group_offsets[0], False


def apply_strategy_to_groups(
    dup_groups: dict[str, list[int]],
    source_bytes: bytes,
    strategy: KeeperStrategy,
    params: StrategyParams = StrategyParams(),
) -> tuple[dict[str, int], int]:
    """Pick keepers for every group; return ``({group_key: offset}, matched_count)``.

    ``matched_count`` is the number of groups where the strategy's
    criterion actually selected a record (vs falling back to first
    occurrence). Useful for the UI message: "matched 247 of 4000
    groups; the rest fell back to first-occurrence."
    """
    keepers: dict[str, int] = {}
    matched = 0
    for key, offsets in dup_groups.items():
        offset, matched_strategy = pick_keeper(
            offsets, source_bytes, strategy, params,
        )
        keepers[key] = offset
        if matched_strategy:
            matched += 1
    return keepers, matched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field_count(record: Optional[pymarc.Record]) -> int:
    if record is None:
        return -1  # unparseable records lose ties to parseable ones
    return len(record.fields)


def _count_tag(record: Optional[pymarc.Record], tag: str) -> int:
    if record is None:
        return -1
    return len(record.get_fields(tag))


def _max_by_with_score(
    group_offsets: list[int],
    source_bytes: bytes,
    score_fn,
) -> tuple[int, int]:
    """Pick the offset whose record scores highest; tie-break = first.

    Returns ``(offset, score)`` so callers can decide whether a tied
    or zero-score result deserves UI treatment.
    """
    best_offset = group_offsets[0]
    best_score = score_fn(_record_at(source_bytes, best_offset))
    for offset in group_offsets[1:]:
        score = score_fn(_record_at(source_bytes, offset))
        if score > best_score:
            best_score = score
            best_offset = offset
    return best_offset, best_score


def _first_matching(
    group_offsets: list[int],
    source_bytes: bytes,
    params: StrategyParams,
) -> tuple[int, bool]:
    """Return ``(offset, matched)``: the first offset whose ``tag$sub`` value
    matches ``params.pattern``, plus a flag indicating whether ANY group
    member matched.

    Falls back to ``(group_offsets[0], False)`` when no member matches
    (or when params are incomplete / regex compile fails). The compile
    fallback is defensive — render-layer pre-validation via
    :func:`validate_params` should have caught a bad pattern first.
    """
    tag = params.tag
    pattern = params.pattern
    if not tag or not pattern:
        return group_offsets[0], False
    flags = 0 if params.case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        return group_offsets[0], False

    for offset in group_offsets:
        record = _record_at(source_bytes, offset)
        if record is None:
            continue
        for field in record.get_fields(tag):
            haystacks: list[str] = []
            if field.is_control_field():
                haystacks.append(field.data or "")
            elif params.subfield:
                haystacks.extend(field.get_subfields(params.subfield))
            else:
                haystacks.extend(sf.value for sf in field.subfields)
            for hay in haystacks:
                if compiled.search(hay):
                    return offset, True
    return group_offsets[0], False
