"""Render `pymarc.Record`s as MarcEdit-style `.mrk` text.

Single-source wrapper over `str(record)` so callers don't depend on
pymarc's `__str__` shape directly. Output always uses `$` as the
subfield delimiter (the parser accepts both `$` and `|` on input but
this writer is canonical).

A multi-record batch is joined with one blank line between records to
mirror the source format produced by MarcEdit's "Edit MARC Records"
export and consumed by `parse_mrk`.
"""

from __future__ import annotations

from typing import Iterable

from pymarc import Record


_RECORD_SEPARATOR = "\n\n"


def render_record_mrk(record: Record) -> str:
    """Return the `.mrk` text for a single record.

    No trailing newline — let callers control how records are joined.
    """
    # pymarc's `__str__` already emits `=LDR  ...` and `=TAG  ...`
    # lines with `$` subfield delimiters. We delegate, but route
    # through this function so any future encoding tweaks land in
    # exactly one place.
    return str(record)


def render_records_mrk(records: Iterable[Record]) -> str:
    """Return the `.mrk` text for a batch of records.

    Records are separated by a single blank line so `parse_mrk` can
    pick them apart again deterministically. Trailing newline added so
    the resulting blob round-trips cleanly through file editors that
    auto-insert one.
    """
    chunks = [render_record_mrk(r) for r in records]
    return _RECORD_SEPARATOR.join(chunks) + "\n"
