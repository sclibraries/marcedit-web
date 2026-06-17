"""Tests for marcedit_web.lib.marc_diff low-level buffer iteration."""

from __future__ import annotations

import itertools

import pytest

from marcedit_web.lib.marc_diff import _iter_records


def test_iter_records_rejects_nonadvancing_zero_length():
    """A declared record length of 0 must raise, not loop forever.

    The 5-byte MARC length field controls how far the cursor advances. A crafted
    length of ``00000`` leaves ``pos`` unchanged and spins ``_iter_records``
    forever, pinning the single Streamlit worker thread at 100% CPU — an
    unauthenticated-reachable DoS via any uploaded .mrc. It must instead raise
    ``ValueError`` so callers route it to the already-handled malformed path
    (the same way a truncated/short record is handled). See TASK-072.
    """
    with pytest.raises(ValueError):
        list(_iter_records(b"00000abcde"))


def test_iter_records_rejects_length_below_leader_minimum():
    """Any length below the 24-byte leader cannot be a real record -> raise.

    ``00010`` (10 bytes) does advance the cursor, so it would not loop, but a
    record shorter than the mandatory 24-byte leader is malformed and must be
    rejected rather than yielded as a bogus record.
    """
    with pytest.raises(ValueError):
        list(_iter_records(b"00010" + b"x" * 5))


def test_iter_records_rejects_negative_length():
    """A negative length must raise: ``int(b'-0001')`` is ``-1`` (Python accepts
    the ASCII minus), and without the guard ``pos += -1`` walks the cursor
    backward into a second, distinct infinite loop. ``length < LEADER_LEN``
    catches all negatives too. (TASK-072)
    """
    with pytest.raises(ValueError):
        list(_iter_records(b"-0001" + b"x" * 20))


def test_iter_records_terminates_on_valid_blob():
    """Sanity guard: a well-formed record still iterates and terminates."""
    import pymarc

    rec = pymarc.Record()
    rec.add_field(
        pymarc.Field(
            tag="245",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield(code="a", value="Valid record")],
        )
    )
    blob = rec.as_marc()
    got = list(itertools.islice(_iter_records(blob), 0, 10))
    assert len(got) == 1
    assert got[0][0] == 0  # single record at offset 0
