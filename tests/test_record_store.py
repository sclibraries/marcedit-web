"""Tests for marcedit_web.lib.record_store."""

from __future__ import annotations

import io
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import record_store
from marcedit_web.lib.record_store import RecordLocation, RecordStore


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.mrc"


@pytest.fixture
def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture
def store(fixture_bytes, tmp_path) -> RecordStore:
    return RecordStore.from_bytes(
        fixture_bytes,
        tmp_dir=tmp_path / "rs",
        filename="sample.mrc",
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_from_bytes_indexes_seven_records(store):
    assert store.count() == 7
    assert store.raw_count() == 7
    assert store.malformed_count() == 0
    assert store.filename == "sample.mrc"


def test_from_bytes_writes_temp_file(store, fixture_bytes):
    assert store.path.exists()
    assert store.path.read_bytes() == fixture_bytes


def test_from_bytes_handles_empty(tmp_path):
    s = RecordStore.from_bytes(b"", tmp_dir=tmp_path / "empty")
    assert s.count() == 0
    assert s.raw_count() == 0
    assert s.malformed_count() == 0


def test_from_bytes_handles_truncated(tmp_path):
    s = RecordStore.from_bytes(b"00100abc", tmp_dir=tmp_path / "trunc")
    # Length 100 declared, only 8 bytes total — _iter_records raises,
    # we record one malformed and stop.
    assert s.count() == 0
    assert s.malformed_count() == 1


def test_from_bytes_handles_zero_length_record(tmp_path):
    # Length field 00000 would spin _iter_records forever (CPU DoS) without the
    # guard. from_bytes must treat it as one malformed record and return
    # promptly, exactly like the truncated case above (TASK-072).
    s = RecordStore.from_bytes(b"00000abcde", tmp_dir=tmp_path / "zero")
    assert s.count() == 0
    assert s.raw_count() == 0
    assert s.malformed_count() == 1


def test_from_path_reads_existing_file(tmp_path):
    target = tmp_path / "sample.mrc"
    target.write_bytes(FIXTURE.read_bytes())
    s = RecordStore.from_path(target)
    assert s.count() == 7
    assert s.path == target


def test_from_path_indexes_without_materializing_file(tmp_path, monkeypatch):
    """Persisted reload must not reintroduce full-file RAM copies (TASK-132)."""
    target = tmp_path / "sample.mrc"
    target.write_bytes(FIXTURE.read_bytes())

    def _read_bytes(self):
        raise AssertionError("from_path must not materialize persisted uploads")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)

    s = RecordStore.from_path(target)

    assert s.count() == 7
    assert s.malformed_count() == 0


def test_from_records_builds_fresh_store(store, tmp_path):
    records = list(store.iter_records())
    s2 = RecordStore.from_records(records, tmp_dir=tmp_path / "rebuilt")
    assert s2.count() == 7


class _ChunkOnlyFile(io.BytesIO):
    """File object that forbids whole-body materialization.

    Mirrors how ``RecordStore.from_file`` must consume Streamlit's
    UploadedFile (TASK-132): bounded ``read(n)`` calls only. A
    ``getvalue()`` or unbounded ``read()`` would put the entire upload
    back in RAM, defeating the point of streaming ingest — the memory
    blowout implicated in the TASK-117 outage.
    """

    def getvalue(self):
        raise AssertionError("from_file must not call getvalue()")

    def read(self, size=-1):
        assert size is not None and 0 < size <= 8 * 1024 * 1024, (
            f"unbounded read({size}) materializes the whole upload"
        )
        return super().read(size)


def test_from_file_matches_from_bytes(fixture_bytes, tmp_path, store):
    s = RecordStore.from_file(
        _ChunkOnlyFile(fixture_bytes),
        tmp_dir=tmp_path / "ff",
        filename="sample.mrc",
    )
    assert s.count() == store.count() == 7
    assert s.malformed_count() == 0
    assert s.filename == "sample.mrc"
    assert s.path.read_bytes() == fixture_bytes
    assert s.to_mrc_bytes() == store.to_mrc_bytes()


def test_from_file_rewinds_before_reading(fixture_bytes, tmp_path):
    # The uploader widget may hand over a file object whose position is
    # at EOF (a previous consumer read it); ingest must not silently
    # produce an empty store because of that.
    fh = _ChunkOnlyFile(fixture_bytes)
    fh.seek(0, io.SEEK_END)
    s = RecordStore.from_file(fh, tmp_dir=tmp_path / "rw")
    assert s.count() == 7


def test_from_file_handles_empty(tmp_path):
    s = RecordStore.from_file(_ChunkOnlyFile(b""), tmp_dir=tmp_path / "empty")
    assert s.count() == 0
    assert s.malformed_count() == 0


def test_from_file_handles_truncated(tmp_path):
    # Same malformed semantics as from_bytes: stop the walk, count one.
    s = RecordStore.from_file(_ChunkOnlyFile(b"00100abc"), tmp_dir=tmp_path / "tr")
    assert s.count() == 0
    assert s.malformed_count() == 1


# ---------------------------------------------------------------------------
# Lazy parse + reads
# ---------------------------------------------------------------------------


def test_get_returns_pymarc_record(store):
    r = store.get(0)
    assert isinstance(r, pymarc.Record)
    assert r.get("001").data == "1587455634"


def test_get_out_of_range_returns_none(store):
    assert store.get(99) is None
    assert store.get(-1) is None


def test_get_last_record_does_not_walk_the_store(store, monkeypatch):
    """Random access must parse only the requested record, regardless of index."""
    expected = list(store.iter_records())[-1].get("001").data

    def _sequential_read(*_args, **_kwargs):
        raise AssertionError("get must not scan through iter_records")

    monkeypatch.setattr(store, "iter_records", _sequential_read)

    assert store.get(store.count() - 1).get("001").data == expected


def test_iter_records_yields_all(store):
    records = list(store.iter_records())
    assert len(records) == 7
    # Verify identifier order matches the fixture.
    ids = [r.get("001").data for r in records]
    assert ids[0] == "1587455634"
    assert ids[1] == "1579014042"


def test_iter_records_supports_slice(store):
    records = list(store.iter_records(start=2, stop=5))
    assert len(records) == 3


def test_iter_records_lazy_parse(store):
    """Building the store does not eagerly parse pymarc Records."""
    # We can't directly inspect "no records were parsed" but we can show
    # that iter_records produces fresh objects each call (no caching).
    a = list(store.iter_records())
    b = list(store.iter_records())
    # Records compare equal by content but are separate instances.
    assert a is not b
    assert a[0] is not b[0]


# ---------------------------------------------------------------------------
# Edits: replace, delete, append
# ---------------------------------------------------------------------------


def test_replace_visible_on_next_get(store):
    edited = pymarc.Record()
    edited.leader = pymarc.Leader("00000nam a2200000 a 4500")
    edited.add_field(pymarc.Field(tag="001", data="EDITED"))
    store.replace(0, edited)
    assert store.get(0).get("001").data == "EDITED"
    # Other records unchanged.
    assert store.get(1).get("001").data == "1579014042"


def test_content_mutations_advance_revision(store):
    """Preview staleness needs a cheap generation token for every mutation."""
    edited = pymarc.Record()
    edited.leader = pymarc.Leader("00000nam a2200000 a 4500")
    edited.add_field(pymarc.Field(tag="001", data="EDITED"))

    assert store.revision == 0
    store.replace(0, edited)
    assert store.revision == 1
    store.delete(1)
    assert store.revision == 2
    store.append(edited)
    assert store.revision == 3


def test_replace_survives_to_mrc_bytes_round_trip(store):
    edited = pymarc.Record()
    edited.leader = pymarc.Leader("00000nam a2200000 a 4500")
    edited.add_field(pymarc.Field(tag="001", data="EDITED"))
    store.replace(0, edited)
    raw = store.to_mrc_bytes()
    reread = list(pymarc.MARCReader(io.BytesIO(raw), to_unicode=True, permissive=True))
    assert reread[0].get("001").data == "EDITED"
    assert reread[1].get("001").data == "1579014042"


def test_delete_decrements_count_and_shifts_indices(store):
    store.delete(2)
    assert store.count() == 6
    # Live index 2 should now point at what was originally index 3.
    ids = [r.get("001").data for r in store.iter_records()]
    assert len(ids) == 6
    # Original ordering: 1587455634, 1579014042, 1456..., 1234..., 1789..., ...
    # We don't know the exact 001 list, just that index 2 changed.
    expected_after_delete = ids[2]
    fresh_store = RecordStore.from_bytes(
        FIXTURE.read_bytes(), tmp_dir=store.path.parent.parent / "fresh",
    )
    original_at_3 = list(fresh_store.iter_records())[3].get("001").data
    assert expected_after_delete == original_at_3


def test_append_adds_to_live_sequence(store):
    new = pymarc.Record()
    new.leader = pymarc.Leader("00000nam a2200000 a 4500")
    new.add_field(pymarc.Field(tag="001", data="APPENDED"))
    store.append(new)
    assert store.count() == 8
    assert store.get(7).get("001").data == "APPENDED"


def test_replace_all_swaps_the_whole_sequence(store, tmp_path):
    new_records = []
    for i in range(3):
        r = pymarc.Record()
        r.leader = pymarc.Leader("00000nam a2200000 a 4500")
        r.add_field(pymarc.Field(tag="001", data=f"NEW{i}"))
        new_records.append(r)
    store.replace_all(new_records)
    assert store.count() == 3
    ids = [r.get("001").data for r in store.iter_records()]
    assert ids == ["NEW0", "NEW1", "NEW2"]


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_to_mrc_bytes_round_trips_unchanged_batch(fixture_bytes, tmp_path):
    s = RecordStore.from_bytes(fixture_bytes, tmp_dir=tmp_path / "rt")
    raw = s.to_mrc_bytes()
    reread = list(pymarc.MARCReader(io.BytesIO(raw), to_unicode=True, permissive=True))
    original = list(pymarc.MARCReader(io.BytesIO(fixture_bytes), to_unicode=True, permissive=True))
    assert [r.get("001").data for r in reread] == [r.get("001").data for r in original]


def test_to_mrc_bytes_round_trips_mixed_edits(store):
    # Replace record 0, delete record 2, append a new record.
    edited = pymarc.Record()
    edited.leader = pymarc.Leader("00000nam a2200000 a 4500")
    edited.add_field(pymarc.Field(tag="001", data="EDITED-0"))
    store.replace(0, edited)
    store.delete(2)
    appended = pymarc.Record()
    appended.leader = pymarc.Leader("00000nam a2200000 a 4500")
    appended.add_field(pymarc.Field(tag="001", data="APPENDED"))
    store.append(appended)

    raw = store.to_mrc_bytes()
    reread = list(pymarc.MARCReader(io.BytesIO(raw), to_unicode=True, permissive=True))
    ids = [r.get("001").data for r in reread]
    assert ids[0] == "EDITED-0"
    assert ids[-1] == "APPENDED"
    assert len(ids) == 7  # 7 original - 1 deleted + 1 appended


# ---------------------------------------------------------------------------
# Stage 20: write_mrc_to streaming output
# ---------------------------------------------------------------------------


def test_write_mrc_to_round_trips_unchanged_batch(fixture_bytes, tmp_path):
    """Streaming write reads back as the same N records via MARCReader."""
    s = RecordStore.from_bytes(fixture_bytes, tmp_dir=tmp_path / "wm")
    out_path = tmp_path / "out.mrc"
    written = s.write_mrc_to(out_path)
    assert written > 0
    assert out_path.stat().st_size == written
    with out_path.open("rb") as fh:
        reread = list(pymarc.MARCReader(fh, to_unicode=True, permissive=True))
    assert len(reread) == 7
    original = list(pymarc.MARCReader(io.BytesIO(fixture_bytes), to_unicode=True, permissive=True))
    assert [r.get("001").data for r in reread] == [r.get("001").data for r in original]


def test_write_mrc_to_reflects_edits(store, tmp_path):
    """Live edits (replace, delete, append) flow through write_mrc_to."""
    edited = pymarc.Record()
    edited.leader = pymarc.Leader("00000nam a2200000 a 4500")
    edited.add_field(pymarc.Field(tag="001", data="EDITED-0"))
    store.replace(0, edited)
    store.delete(2)
    appended = pymarc.Record()
    appended.leader = pymarc.Leader("00000nam a2200000 a 4500")
    appended.add_field(pymarc.Field(tag="001", data="APPENDED"))
    store.append(appended)

    out_path = tmp_path / "edited.mrc"
    store.write_mrc_to(out_path)
    with out_path.open("rb") as fh:
        reread = list(pymarc.MARCReader(fh, to_unicode=True, permissive=True))
    ids = [r.get("001").data for r in reread]
    assert ids[0] == "EDITED-0"
    assert ids[-1] == "APPENDED"
    assert len(ids) == 7


def test_write_mrc_to_creates_parent_dir(fixture_bytes, tmp_path):
    """Missing parent directories are created on demand."""
    s = RecordStore.from_bytes(fixture_bytes, tmp_dir=tmp_path / "wm2")
    out_path = tmp_path / "newdir" / "subdir" / "out.mrc"
    s.write_mrc_to(out_path)
    assert out_path.exists()


def test_persist_to_disk_survives_restore(store):
    """Saved edits must update the backing file used after browser refresh."""
    edited = pymarc.Record()
    edited.leader = pymarc.Leader("00000nam a2200000 a 4500")
    edited.add_field(pymarc.Field(tag="001", data="PERSISTED-0"))

    store.replace(0, edited)
    store.persist_to_disk()

    restored = RecordStore.from_path(store.path)
    assert restored.get(0).get("001").data == "PERSISTED-0"
    assert store.get(0).get("001").data == "PERSISTED-0"


def test_persist_to_disk_reindexes_without_materializing_file(store, monkeypatch):
    """Committing an edit must not allocate another full-batch byte string."""
    edited = pymarc.Record()
    edited.leader = pymarc.Leader("00000nam a2200000 a 4500")
    edited.add_field(pymarc.Field(tag="001", data="PERSISTED-0"))
    store.replace(0, edited)

    def _read_bytes(self):
        raise AssertionError("persist_to_disk must reindex from the file")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)

    store.persist_to_disk()

    assert store.get(0).get("001").data == "PERSISTED-0"


def test_replace_from_path_adopts_batch_without_consuming_source(
    store, fixture_bytes, tmp_path
):
    """Batch apply keeps the stable upload path and a reusable result artifact."""
    replacement = RecordStore.from_bytes(
        fixture_bytes,
        tmp_dir=tmp_path / "replacement-store",
        filename="replacement.mrc",
    )
    replacement.delete(0)
    source_path = tmp_path / "batch-result.mrc"
    replacement.write_mrc_to(source_path)
    source_bytes = source_path.read_bytes()
    stable_path = store.path

    written = store.replace_from_path(source_path)

    assert written == len(source_bytes)
    assert store.path == stable_path
    assert store.count() == 6
    assert store.revision == 1
    assert source_path.read_bytes() == source_bytes


# ---------------------------------------------------------------------------
# RecordLocation
# ---------------------------------------------------------------------------


def test_record_location_is_frozen():
    loc = RecordLocation(offset=0, length=100)
    with pytest.raises(Exception):  # noqa: PT011 - FrozenInstanceError
        loc.offset = 5  # type: ignore[misc]
