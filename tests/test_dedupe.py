"""Tests for the in-file dedupe flow (Stage 15).

The render function itself is exercised by Playwright; here we cover
the underlying ``marc_diff`` plumbing the render layer depends on:
``index_buffer`` surfaces within-buffer duplicates, and
``write_subset_to_bytes`` materializes the non-keepers into a
readable ``.mrc``.
"""

from __future__ import annotations

import io

import pymarc
import pytest

from marcedit_web.lib import marc_diff
from marcedit_web.lib.marc_diff import OCOLC_SPEC


def _record(oclc: str, title: str, control_001: str) -> pymarc.Record:
    """Build a small synthetic record with the given OCLC 035 $a + 245 $a."""
    r = pymarc.Record()
    r.leader = pymarc.Leader("00000nam a2200000 a 4500")
    r.add_field(pymarc.Field(tag="001", data=control_001))
    r.add_field(
        pymarc.Field(
            tag="008",
            data="180706s2013    nyu     ob    001 0 eng d",
        )
    )
    r.add_field(
        pymarc.Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield("a", f"(OCoLC){oclc}")],
        )
    )
    r.add_field(
        pymarc.Field(
            tag="245",
            indicators=["1", "0"],
            subfields=[pymarc.Subfield("a", title)],
        )
    )
    return r


def _serialize(records: list[pymarc.Record]) -> bytes:
    buf = io.BytesIO()
    writer = pymarc.MARCWriter(buf)
    for r in records:
        writer.write(r)
    return buf.getvalue()


@pytest.fixture
def dupe_fixture() -> bytes:
    """5-record fixture: records 1+3 share OCoLC `111`; the rest are unique.

    Expected outcome from `index_buffer` with OCOLC_SPEC:
      * `duplicate_offsets = {"111": [offset_of_r1, offset_of_r3]}` — one group.
      * `total_records == 5`.
    """
    records = [
        _record(oclc="111", title="First copy",  control_001="rec-a"),
        _record(oclc="222", title="Unique two",  control_001="rec-b"),
        _record(oclc="111", title="Second copy", control_001="rec-c"),
        _record(oclc="333", title="Unique four", control_001="rec-d"),
        _record(oclc="444", title="Unique five", control_001="rec-e"),
    ]
    return _serialize(records)


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def test_index_buffer_surfaces_one_duplicate_group(dupe_fixture):
    result = marc_diff.index_buffer("loaded", dupe_fixture, [OCOLC_SPEC])
    assert result.total_records == 5
    assert len(result.duplicate_offsets) == 1
    key = next(iter(result.duplicate_offsets))
    # OCOLC_SPEC strips the `(OCoLC)` prefix by default; key is bare digits.
    assert key == "111"
    offsets = result.duplicate_offsets[key]
    assert len(offsets) == 2


def test_index_buffer_orders_offsets_by_position(dupe_fixture):
    result = marc_diff.index_buffer("loaded", dupe_fixture, [OCOLC_SPEC])
    offsets = result.duplicate_offsets["111"]
    assert offsets[0] < offsets[1]


def test_no_duplicates_when_keys_unique():
    """A fixture where every record has a different OCoLC produces zero groups."""
    records = [
        _record(oclc=f"{n}", title=f"Record {n}", control_001=f"r{n}")
        for n in (100, 200, 300, 400)
    ]
    data = _serialize(records)
    result = marc_diff.index_buffer("loaded", data, [OCOLC_SPEC])
    assert result.duplicate_offsets == {}


# ---------------------------------------------------------------------------
# Deletes export
# ---------------------------------------------------------------------------


def test_write_subset_yields_only_non_keepers(dupe_fixture):
    """Pick the FIRST occurrence as keeper; the second goes into deletes."""
    result = marc_diff.index_buffer("loaded", dupe_fixture, [OCOLC_SPEC])
    offsets = result.duplicate_offsets["111"]
    keeper, non_keeper = offsets[0], offsets[1]

    delete_locations = [("loaded", non_keeper)]
    deletes_bytes = marc_diff.write_subset_to_bytes(
        delete_locations, {"loaded": dupe_fixture}
    )

    reread = list(
        pymarc.MARCReader(io.BytesIO(deletes_bytes), to_unicode=True, permissive=True)
    )
    assert len(reread) == 1
    # The kept record is "First copy" (001 = "rec-a"); the export should
    # contain only the SECOND copy (001 = "rec-c").
    assert reread[0].get("001").data == "rec-c"
    assert reread[0].get("245").get_subfields("a") == ["Second copy"]


def test_keeper_choice_affects_export(dupe_fixture):
    """Flipping which offset is keeper flips which record lands in deletes."""
    result = marc_diff.index_buffer("loaded", dupe_fixture, [OCOLC_SPEC])
    offsets = result.duplicate_offsets["111"]

    # Variant 1: keeper = first → export contains the SECOND copy.
    deletes_v1 = marc_diff.write_subset_to_bytes(
        [("loaded", offsets[1])], {"loaded": dupe_fixture}
    )
    reread_v1 = list(pymarc.MARCReader(io.BytesIO(deletes_v1), to_unicode=True, permissive=True))
    assert reread_v1[0].get("001").data == "rec-c"

    # Variant 2: keeper = second → export contains the FIRST copy.
    deletes_v2 = marc_diff.write_subset_to_bytes(
        [("loaded", offsets[0])], {"loaded": dupe_fixture}
    )
    reread_v2 = list(pymarc.MARCReader(io.BytesIO(deletes_v2), to_unicode=True, permissive=True))
    assert reread_v2[0].get("001").data == "rec-a"


def test_export_size_scales_with_group_count():
    """3-way duplicate group → 2 records in the deletes export."""
    records = [
        _record(oclc="555", title="copy A", control_001="r1"),
        _record(oclc="555", title="copy B", control_001="r2"),
        _record(oclc="555", title="copy C", control_001="r3"),
        _record(oclc="999", title="unique", control_001="r4"),
    ]
    data = _serialize(records)
    result = marc_diff.index_buffer("loaded", data, [OCOLC_SPEC])
    offsets = result.duplicate_offsets["555"]
    assert len(offsets) == 3
    # Keep first, delete the other two.
    deletes = marc_diff.write_subset_to_bytes(
        [("loaded", o) for o in offsets[1:]],
        {"loaded": data},
    )
    reread = list(pymarc.MARCReader(io.BytesIO(deletes), to_unicode=True, permissive=True))
    assert {r.get("001").data for r in reread} == {"r2", "r3"}
