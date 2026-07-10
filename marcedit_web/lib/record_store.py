"""Disk-backed MARC record store with lazy pymarc parsing.

The crash on a 100K-record upload (v1 ticket TASK-011) had two root
causes: eagerly parsing every record into a ``pymarc.Record`` and then
serializing the whole batch as one ``.mrk`` string. This module solves
the first half — records are stored as raw bytes on disk with an
in-memory ``(offset, length)`` index, and pymarc objects are produced
only on demand.

Storage layout
--------------

* The original ``.mrc`` blob is written once to a session-temp file at
  ``<tmp_dir>/upload.mrc`` (caller picks ``tmp_dir``).
* The offsets index ``list[RecordLocation]`` is built in a single
  linear pass over the bytes via ``marc_diff._iter_records``.
* A compact list maps live positions directly to raw locations. Edits,
  deletes, and appends are tracked in an override map and appended list.
* ``to_mrc_bytes`` walks the merged index, pulling each record from
  the override map or reading + parsing the on-disk bytes, then
  re-emits via ``pymarc.MARCWriter``.

Memory budget at 100K records: ``list[RecordLocation]`` is ~1.6 MB
(two ints per record + dataclass overhead). Override map is empty
until the user actually edits something. Raw bytes never sit in
``st.session_state``.
"""

from __future__ import annotations

import io
import logging
import mmap
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import pymarc

from .marc_diff import _iter_records

logger = logging.getLogger("marcedit_web.record_store")

# Chunk size for streaming an upload to disk (TASK-132). 1 MB keeps the
# per-copy RAM footprint negligible without measurable copy slowdown.
_COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RecordLocation:
    """Byte location of a single record in the underlying ``.mrc`` blob."""

    offset: int
    length: int


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class RecordStore:
    """Disk-backed, lazy-parsed view over a MARC blob.

    Constructed via :py:meth:`from_bytes` or :py:meth:`from_path`. The
    instance is safe to store in ``st.session_state`` — it holds a
    ``pathlib.Path`` to the underlying file, a small offsets list, an
    override dict, and bookkeeping counters. No pymarc Records survive
    in the store unless the caller edits one via :py:meth:`replace` or
    :py:meth:`append`.
    """

    def __init__(
        self,
        *,
        path: Path,
        locations: list[RecordLocation],
        malformed: int,
        filename: Optional[str] = None,
    ) -> None:
        self._path = path
        self._locations: list[RecordLocation] = locations
        self._live_raw_indices: list[int] = list(range(len(locations)))
        self._overrides: dict[int, Optional[pymarc.Record]] = {}
        self._appended: list[pymarc.Record] = []
        self._malformed = malformed
        self._filename = filename
        self._revision = 0

    # ------------------------------------------------------------------ factories

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        tmp_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> "RecordStore":
        """Build a store from in-memory MARC bytes.

        Writes the bytes to ``<tmp_dir>/upload.mrc`` (creates a fresh
        temp dir when ``tmp_dir`` is None) and builds the offsets index
        in a single linear pass. Truncated / malformed prefixes increment
        the malformed counter but do not raise — best-effort recovery
        matches the rest of the codebase.
        """
        if tmp_dir is None:
            tmp_dir = Path(tempfile.mkdtemp(prefix="marcedit-web-records-"))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path = tmp_dir / "upload.mrc"
        path.write_bytes(data or b"")
        locations, malformed = _index_bytes(data or b"")
        logger.info(
            "RecordStore built: %d records, %d malformed, %s bytes on disk",
            len(locations), malformed, len(data or b""),
        )
        return cls(
            path=path,
            locations=locations,
            malformed=malformed,
            filename=filename,
        )

    @classmethod
    def from_file(
        cls,
        fileobj,
        *,
        tmp_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> "RecordStore":
        """Build a store by chunk-copying an open binary file to disk.

        Streaming counterpart to :py:meth:`from_bytes` (TASK-132): the
        payload reaches ``<tmp_dir>/upload.mrc`` via bounded reads and
        the offsets index is built over an mmap of the on-disk bytes,
        so peak memory stays O(chunk) instead of O(file). Rewinds
        ``fileobj`` first — the uploader widget may hand it over at EOF.
        """
        if tmp_dir is None:
            tmp_dir = Path(tempfile.mkdtemp(prefix="marcedit-web-records-"))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path = tmp_dir / "upload.mrc"
        fileobj.seek(0)
        with open(path, "wb") as out:
            shutil.copyfileobj(fileobj, out, _COPY_CHUNK_BYTES)
        size = path.stat().st_size
        locations, malformed = _index_path(path)
        logger.info(
            "RecordStore built (streamed): %d records, %d malformed, %s bytes on disk",
            len(locations), malformed, size,
        )
        return cls(
            path=path,
            locations=locations,
            malformed=malformed,
            filename=filename,
        )

    @classmethod
    def from_path(cls, path: Path) -> "RecordStore":
        """Build a store from an existing on-disk ``.mrc``.

        The file is left in place; the store points at it directly.
        Useful for tests + future cross-session persistence.
        """
        locations, malformed = _index_path(path)
        return cls(
            path=path,
            locations=locations,
            malformed=malformed,
            filename=path.name,
        )

    @classmethod
    def from_records(
        cls,
        records: list[pymarc.Record],
        *,
        tmp_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> "RecordStore":
        """Build a fresh store from an in-memory record list.

        Used by the Tasks page after running transforms — the runner
        produces a new ``list[pymarc.Record]`` which becomes the source
        of a fresh store + downloadable ``.mrc``.
        """
        buf = io.BytesIO()
        writer = pymarc.MARCWriter(buf)
        for r in records:
            writer.write(r)
        return cls.from_bytes(buf.getvalue(), tmp_dir=tmp_dir, filename=filename)

    # ------------------------------------------------------------------ basics

    @property
    def filename(self) -> Optional[str]:
        return self._filename

    @property
    def path(self) -> Path:
        return self._path

    @property
    def revision(self) -> int:
        """Monotonic content generation for invalidating derived state."""
        return self._revision

    def malformed_count(self) -> int:
        return self._malformed

    def count(self) -> int:
        """Number of LIVE records (after deletes and appends)."""
        return len(self._live_raw_indices) + len(self._appended)

    def raw_count(self) -> int:
        """Number of records originally indexed (ignores edits)."""
        return len(self._locations)

    # ------------------------------------------------------------------ reads

    def get(self, idx: int) -> Optional[pymarc.Record]:
        """Return the record at 0-based ``idx`` after edits / deletes / appends.

        ``idx`` indexes into the LIVE sequence (so it skips deletions).
        Returns ``None`` if ``idx`` is out of range.
        """
        raw_idx = self._raw_idx_for_live(idx)
        if raw_idx is None:
            return None
        if raw_idx >= len(self._locations):
            return self._appended[raw_idx - len(self._locations)]
        if raw_idx in self._overrides:
            return self._overrides[raw_idx]
        with self._path.open("rb") as fh:
            return self._read_raw_record(fh, raw_idx)

    def iter_records(
        self, start: int = 0, stop: Optional[int] = None
    ) -> Iterator[pymarc.Record]:
        """Yield live records in order.

        ``start`` and ``stop`` are 0-based, ``stop`` exclusive. Half-open,
        ``slice``-style. Deleted records are skipped; appended records
        come after the underlying-file records.

        Opens the underlying file once per iter pass for batched record
        reads — pymarc parses each slice independently.
        """
        total = self.count()
        first = max(0, start)
        last = total if stop is None else min(total, max(first, stop))
        raw_live_count = len(self._live_raw_indices)
        raw_stop = min(last, raw_live_count)

        if first < raw_stop:
            with self._path.open("rb") as fh:
                for live_idx in range(first, raw_stop):
                    raw_idx = self._live_raw_indices[live_idx]
                    if raw_idx in self._overrides:
                        record = self._overrides[raw_idx]
                    else:
                        record = self._read_raw_record(fh, raw_idx)
                    if record is not None:
                        yield record

        appended_start = max(0, first - raw_live_count)
        appended_stop = max(0, last - raw_live_count)
        for appended_idx in range(appended_start, appended_stop):
            yield self._appended[appended_idx]

    # ------------------------------------------------------------------ writes

    def replace(self, idx: int, record: pymarc.Record) -> None:
        """Replace the record at LIVE 0-based ``idx`` with ``record``.

        Raises ``IndexError`` if ``idx`` is out of range.
        """
        raw_idx = self._raw_idx_for_live(idx)
        if raw_idx is None:
            raise IndexError(f"live record index {idx} out of range")
        if raw_idx < len(self._locations):
            self._overrides[raw_idx] = record
        else:
            self._appended[raw_idx - len(self._locations)] = record
        self._revision += 1

    def delete(self, idx: int) -> None:
        """Tombstone the record at LIVE 0-based ``idx``.

        Subsequent ``count()`` calls decrement; the tombstone survives
        through ``to_mrc_bytes()`` (i.e. the deleted record does not
        appear in the output).
        """
        raw_idx = self._raw_idx_for_live(idx)
        if raw_idx is None:
            raise IndexError(f"live record index {idx} out of range")
        if raw_idx < len(self._locations):
            self._live_raw_indices.pop(idx)
            self._overrides[raw_idx] = None
        else:
            # Appended record — remove from the appended list.
            self._appended.pop(raw_idx - len(self._locations))
        self._revision += 1

    def append(self, record: pymarc.Record) -> None:
        """Add ``record`` to the end of the live sequence."""
        self._appended.append(record)
        self._revision += 1

    def replace_all(self, records: list[pymarc.Record]) -> None:
        """Replace the entire live sequence with ``records``.

        Equivalent to ``store.delete(i)`` over every live record then
        appending each new one. Used by MarcEditor's Save flow.
        """
        # Tombstone every original record; clear appended list.
        for raw_idx in range(len(self._locations)):
            self._overrides[raw_idx] = None
        self._live_raw_indices.clear()
        self._appended = list(records)
        self._revision += 1

    # ------------------------------------------------------------------ output

    def to_mrc_bytes(self) -> bytes:
        """Serialize the live sequence to a fresh ``.mrc`` blob.

        Holds the whole batch in memory; prefer :py:meth:`write_mrc_to`
        for any path that doesn't need a bytes return (the Tasks /
        Dedupe pages stream to disk via that helper).
        """
        buf = io.BytesIO()
        writer = pymarc.MARCWriter(buf)
        for record in self.iter_records():
            writer.write(record)
        return buf.getvalue()

    def write_mrc_to(self, path: Path) -> int:
        """Stream the live record sequence to ``path``; return byte count.

        Avoids the full-batch ``io.BytesIO`` materialization that
        :py:meth:`to_mrc_bytes` does. At 100K records this drops peak
        memory by ~the size of the MRC blob (typically 50–200 MB).
        Callers that need bytes downstream should use
        :py:meth:`to_mrc_bytes`; callers that hand the file to another
        process (sandbox) or seek-read it (dedupe per-record render)
        should prefer this.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("wb") as fh:
            writer = pymarc.MARCWriter(fh)
            for record in self.iter_records():
                writer.write(record)
        written = path.stat().st_size
        return written

    def persist_to_disk(self) -> int:
        """Rewrite this store's backing file with the current live records.

        ``write_mrc_to(self.path)`` is unsafe because iterating records reads
        from ``self.path``; opening that same file for write would truncate it
        before unchanged records can be copied. Write to a sibling temp file
        first, then atomically replace the backing file and rebuild the index.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.tmp")
        written = self.write_mrc_to(temp_path)
        os.replace(temp_path, self._path)
        self._reindex_backing_file()
        return written

    def replace_from_path(self, source_path: Path) -> int:
        """Copy ``source_path`` over the stable backing file and reindex it.

        The source remains available to diff/history callers. Copying to a
        sibling temporary file before ``os.replace`` prevents readers from
        observing a partial batch and works when the source is on another
        filesystem.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        temp_path = self._path.with_name(f".{self._path.name}.replace.tmp")
        try:
            with source_path.open("rb") as source, temp_path.open("wb") as target:
                shutil.copyfileobj(source, target, _COPY_CHUNK_BYTES)
            written = temp_path.stat().st_size
            os.replace(temp_path, self._path)
        finally:
            temp_path.unlink(missing_ok=True)
        self._reindex_backing_file()
        self._revision += 1
        return written

    # ------------------------------------------------------------------ helpers

    def _raw_idx_for_live(self, live_idx: int) -> Optional[int]:
        """Return the raw/appended index for a live position in O(1)."""
        if live_idx < 0:
            return None
        if live_idx < len(self._live_raw_indices):
            return self._live_raw_indices[live_idx]
        appended_offset = live_idx - len(self._live_raw_indices)
        if 0 <= appended_offset < len(self._appended):
            return len(self._locations) + appended_offset
        return None

    def _read_raw_record(self, fh, raw_idx: int) -> Optional[pymarc.Record]:
        loc = self._locations[raw_idx]
        fh.seek(loc.offset)
        chunk = fh.read(loc.length)
        try:
            return pymarc.Record(data=chunk)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "skipping malformed record at offset %d: %s",
                loc.offset,
                exc,
            )
            return None

    def _reindex_backing_file(self) -> None:
        locations, malformed = _index_path(self._path)
        self._locations = locations
        self._live_raw_indices = list(range(len(locations)))
        self._overrides.clear()
        self._appended.clear()
        self._malformed = malformed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _index_bytes(data: bytes) -> tuple[list[RecordLocation], int]:
    """Walk ``data`` and return (locations, malformed_count).

    Never raises. ``_iter_records`` raises on truncation; we catch and
    stop the walk, treating any remaining bytes as one malformed record.
    """
    locations: list[RecordLocation] = []
    malformed = 0
    try:
        for offset, chunk in _iter_records(data):
            locations.append(RecordLocation(offset=offset, length=len(chunk)))
    except ValueError as exc:
        logger.warning("stopped indexing at malformed offset: %s", exc)
        malformed += 1
    return locations, malformed


def _index_path(path: Path) -> tuple[list[RecordLocation], int]:
    """Index an MRC path without materializing the file as ``bytes``."""
    if path.stat().st_size == 0:
        return [], 0
    with path.open("rb") as fh:
        with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            return _index_bytes(mm)
