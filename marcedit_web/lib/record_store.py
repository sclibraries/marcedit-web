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
* Edits, deletes, and appends are tracked in an in-memory override
  map ``dict[int, pymarc.Record | None]`` (None = deleted, indices
  beyond ``len(_locations)`` are appended records).
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
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import pymarc

from .marc_diff import _iter_records

logger = logging.getLogger("marcedit_web.record_store")


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
        self._overrides: dict[int, Optional[pymarc.Record]] = {}
        self._appended: list[pymarc.Record] = []
        self._malformed = malformed
        self._filename = filename

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
    def from_path(cls, path: Path) -> "RecordStore":
        """Build a store from an existing on-disk ``.mrc``.

        The file is left in place; the store points at it directly.
        Useful for tests + future cross-session persistence.
        """
        data = path.read_bytes()
        locations, malformed = _index_bytes(data)
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

    def malformed_count(self) -> int:
        return self._malformed

    def count(self) -> int:
        """Number of LIVE records (after deletes and appends)."""
        deletes = sum(1 for v in self._overrides.values() if v is None)
        return len(self._locations) + len(self._appended) - deletes

    def raw_count(self) -> int:
        """Number of records originally indexed (ignores edits)."""
        return len(self._locations)

    # ------------------------------------------------------------------ reads

    def get(self, idx: int) -> Optional[pymarc.Record]:
        """Return the record at 0-based ``idx`` after edits / deletes / appends.

        ``idx`` indexes into the LIVE sequence (so it skips deletions).
        Returns ``None`` if ``idx`` is out of range.
        """
        for live_idx, record in enumerate(self.iter_records()):
            if live_idx == idx:
                return record
        return None

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
        live_idx = 0
        if stop is None:
            stop_or_inf = float("inf")
        else:
            stop_or_inf = stop

        with self._path.open("rb") as fh:
            for raw_idx, loc in enumerate(self._locations):
                if raw_idx in self._overrides:
                    record = self._overrides[raw_idx]
                    if record is None:
                        continue  # deleted
                else:
                    fh.seek(loc.offset)
                    chunk = fh.read(loc.length)
                    try:
                        record = pymarc.Record(data=chunk)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "skipping malformed record at offset %d: %s",
                            loc.offset, exc,
                        )
                        continue
                if live_idx >= start and live_idx < stop_or_inf:
                    yield record
                live_idx += 1
                if live_idx >= stop_or_inf:
                    return

        for record in self._appended:
            if live_idx >= start and live_idx < stop_or_inf:
                yield record
            live_idx += 1
            if live_idx >= stop_or_inf:
                return

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
            self._overrides[raw_idx] = None
        else:
            # Appended record — remove from the appended list.
            self._appended.pop(raw_idx - len(self._locations))

    def append(self, record: pymarc.Record) -> None:
        """Add ``record`` to the end of the live sequence."""
        self._appended.append(record)

    def replace_all(self, records: list[pymarc.Record]) -> None:
        """Replace the entire live sequence with ``records``.

        Equivalent to ``store.delete(i)`` over every live record then
        appending each new one. Used by MarcEditor's Save flow.
        """
        # Tombstone every original record; clear appended list.
        for raw_idx in range(len(self._locations)):
            self._overrides[raw_idx] = None
        self._appended = list(records)

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
        locations, malformed = _index_bytes(self._path.read_bytes())
        self._locations = locations
        self._overrides.clear()
        self._appended.clear()
        self._malformed = malformed
        return written

    # ------------------------------------------------------------------ helpers

    def _raw_idx_for_live(self, live_idx: int) -> Optional[int]:
        """Walk the override map to find the raw index for a LIVE index."""
        if live_idx < 0:
            return None
        live = 0
        for raw_idx in range(len(self._locations)):
            if self._overrides.get(raw_idx, "no-override") is None:
                continue
            if live == live_idx:
                return raw_idx
            live += 1
        # Live indices past the underlying file fall into the appended list.
        appended_offset = live_idx - live
        if 0 <= appended_offset < len(self._appended):
            return len(self._locations) + appended_offset
        return None


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
