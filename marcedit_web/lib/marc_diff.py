"""MARC bibliographic file diff core logic.

Match records on a list of caller-supplied `FieldSpec` entries; optionally
detect content changes for records that match on the key; emit selected
records into an in-memory MARC buffer suitable for download.

The module is designed to run entirely in memory: callers pass `(name, bytes)`
buffers in and receive `bytes` out. No filesystem operations happen here.

Public API:
    FieldSpec(tag, subfield=None, byte_range=None, prefix_filter=None,
              strip_prefix=True)
    OCOLC_SPEC                      # convenience: 035 $a with (OCoLC) filter

    extract_key(record_bytes, specs)      -> tuple[str, ...] | None
    fingerprint_record(bytes, exclude_tags) -> str (sha256 hex)

    IndexResult(...)
    MultiIndexResult(...)
    DiffResult(adds_ids, deletes_ids, common_ids, changed_ids)

    index_buffer(name, data, specs)       -> IndexResult
    index_buffers(buffers, specs)         -> MultiIndexResult
    compute_diff(old, new)                -> DiffResult (changed_ids empty)
    detect_changes(old, new, buffers,
                   common_ids, exclude_tags) -> set[str]
    write_subset_to_bytes(locations, buffers) -> bytes
    write_subset_to_path(locations, buffers, output_path) -> int

    suggest_match_fields(buffers, sample_size=500) -> list[FieldSuggestion]

    discover_marc_files(folder)           -> list[Path]   # convenience
"""

from __future__ import annotations

import difflib
import hashlib
import io
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Literal


LEADER_LEN = 24
DIR_ENTRY_LEN = 12
FIELD_TERMINATOR = 0x1E
RECORD_TERMINATOR = 0x1D
SUBFIELD_DELIM = 0x1F


# ---------------------------------------------------------------------------
# Field specifications
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """Describes how to extract a single value from a MARC record.

    - ``tag``: 3-character MARC tag (e.g. ``"035"``, ``"008"``, ``"050"``).
    - ``subfield``: subfield code (e.g. ``"a"``) for variable data fields.
      Must be None for control fields (``001``-``009``).
    - ``byte_range``: ``(start, end_inclusive)`` for control-field byte ranges
      such as ``008/35-37``. Mutually exclusive with ``subfield``.
    - ``prefix_filter``: only return values whose stripped form starts with
      this prefix (e.g. ``"(OCoLC)"``). When set, the spec skips matching
      subfields/fields until it finds one with the prefix.
    - ``strip_prefix``: if a ``prefix_filter`` is set, strip it from the
      returned value. Defaults to True so the key is the bare identifier.
    """

    tag: str
    subfield: str | None = None
    byte_range: tuple[int, int] | None = None
    prefix_filter: str | None = None
    strip_prefix: bool = True

    def label(self) -> str:
        if self.byte_range is not None:
            s, e = self.byte_range
            return f"{self.tag}/{s}-{e}" if s != e else f"{self.tag}/{s}"
        if self.subfield is not None:
            base = f"{self.tag}${self.subfield}"
            return f"{base}~{self.prefix_filter}" if self.prefix_filter else base
        return self.tag


OCOLC_SPEC = FieldSpec(tag="035", subfield="a", prefix_filter="(OCoLC)")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexResult:
    """Indexes one MARC buffer by the caller-supplied match-key specs.

    - ``offsets[key]``: byte offset of the FIRST record with this match key
      (the one that participates in matching).
    - ``missing_key_offsets``: byte offsets of records that lacked any of
      the required match-field values. Each was given a synthetic key in
      ``offsets``.
    - ``duplicate_offsets[key]``: for keys that occurred more than once
      *within this buffer*, the list of ALL offsets where they appeared
      (length ≥ 2). The first entry is the same as ``offsets[key]``.
    """
    offsets: dict[str, int]
    missing_key_offsets: list[int]
    duplicate_offsets: dict[str, list[int]]
    total_records: int

    @property
    def missing_key_count(self) -> int:
        return len(self.missing_key_offsets)

    @property
    def duplicate_key_count(self) -> int:
        return len(self.duplicate_offsets)


@dataclass(frozen=True)
class MultiIndexResult:
    """Combined index over multiple buffers.

    - ``locations[key] = (buffer_name, byte_offset)`` of the first record
      across all buffers with this key (the one used for matching).
    - ``per_buffer``: original per-buffer IndexResults, preserved so the UI
      can drill into within-buffer warnings.
    - ``cross_buffer_duplicate_locations[key]``: for keys present in more
      than one buffer, ALL ``(buffer_name, offset)`` occurrences across the
      side (length ≥ 2).
    """
    locations: dict[str, tuple[str, int]]
    per_buffer: list[tuple[str, IndexResult]]
    cross_buffer_duplicate_locations: dict[str, list[tuple[str, int]]] = field(
        default_factory=dict
    )

    @property
    def total_records(self) -> int:
        return sum(r.total_records for _, r in self.per_buffer)

    @property
    def missing_key_count(self) -> int:
        return sum(r.missing_key_count for _, r in self.per_buffer)

    @property
    def within_buffer_duplicate_count(self) -> int:
        return sum(r.duplicate_key_count for _, r in self.per_buffer)

    @property
    def cross_buffer_duplicate_count(self) -> int:
        return len(self.cross_buffer_duplicate_locations)

    def all_missing_key_locations(self) -> list[tuple[str, int]]:
        """Aggregate (buffer_name, offset) of every missing-key record."""
        out: list[tuple[str, int]] = []
        for name, r in self.per_buffer:
            for off in r.missing_key_offsets:
                out.append((name, off))
        return out

    def all_within_buffer_duplicates(
        self,
    ) -> list[tuple[str, str, list[int]]]:
        """List (buffer_name, key, [offsets]) for every within-buffer dup."""
        out = []
        for name, r in self.per_buffer:
            for key, offsets in r.duplicate_offsets.items():
                out.append((name, key, offsets))
        return out

    def ids(self) -> set[str]:
        return set(self.locations.keys())


@dataclass(frozen=True)
class DiffResult:
    adds_ids: set[str]
    deletes_ids: set[str]
    common_ids: set[str]
    changed_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class FieldSuggestion:
    """Frequency of a tag/subfield across a sample of records."""
    tag: str
    subfield: str | None
    occurrences: int
    sample_size: int
    sample_value: str | None = None
    is_oclc_prefixed: bool = False

    @property
    def coverage(self) -> float:
        return self.occurrences / self.sample_size if self.sample_size else 0.0


@dataclass(frozen=True)
class CombinedFieldSuggestion:
    """Cross-side view of a candidate match field.

    ``overlap`` is the Jaccard similarity between the SETS of values seen on
    each side: |intersection| / |union|. A high value means the same set of
    values is appearing on both sides — a strong match-key signal.

    ``old_value_set`` and ``new_value_set`` hold the actual sampled values so
    the UI can render a side-by-side comparison. They are frozensets so the
    dataclass stays immutable.
    """
    tag: str
    subfield: str | None
    old_coverage: float
    new_coverage: float
    old_distinct_values: int
    new_distinct_values: int
    shared_values: int
    overlap: float
    sample_value: str | None
    is_oclc_prefixed: bool
    old_value_set: frozenset[str] = frozenset()
    new_value_set: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Low-level MARC byte walkers
# ---------------------------------------------------------------------------


def _iter_directory(record_bytes: bytes) -> Iterator[tuple[bytes, int, int]]:
    """Yield (tag, length, start_relative_to_base) for each directory entry."""
    base = int(record_bytes[12:17])
    i = LEADER_LEN
    while i < base - 1:
        tag = record_bytes[i:i + 3]
        length = int(record_bytes[i + 3:i + 7])
        start = int(record_bytes[i + 7:i + 12])
        yield tag, length, start
        i += DIR_ENTRY_LEN


def _field_bytes(record_bytes: bytes, length: int, start: int) -> bytes:
    """Return the raw bytes of a field, excluding its trailing 0x1E terminator."""
    base = int(record_bytes[12:17])
    data_start = base + start
    return record_bytes[data_start:data_start + length - 1]


def _iter_subfields(field_data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """Yield (code, value) for each subfield in a variable data field's data.

    `field_data` should NOT include the field terminator. Variable data
    fields begin with 2 indicator bytes; this walker skips them.
    """
    j = 2  # skip indicators
    while j < len(field_data):
        if field_data[j] != SUBFIELD_DELIM:
            j += 1
            continue
        code = field_data[j + 1:j + 2]
        j += 2
        end = field_data.find(b"\x1f", j)
        if end == -1:
            end = len(field_data)
        yield code, field_data[j:end]
        j = end


# ---------------------------------------------------------------------------
# Per-spec value extraction
# ---------------------------------------------------------------------------


def _extract_for_spec(record_bytes: bytes, spec: FieldSpec) -> str | None:
    """Apply one FieldSpec to a record and return the extracted string or None."""
    target_tag = spec.tag.encode("ascii")
    prefix_b = spec.prefix_filter.encode("ascii") if spec.prefix_filter else None

    for tag, length, start in _iter_directory(record_bytes):
        if tag != target_tag:
            continue
        field_data = _field_bytes(record_bytes, length, start)

        if spec.byte_range is not None:
            # Control field: no indicators, no subfields, just raw bytes.
            s, e = spec.byte_range
            if e + 1 > len(field_data):
                return None
            return field_data[s:e + 1].decode("utf-8", errors="replace")

        if spec.subfield is None:
            # Whole control field (e.g. 001, 005, 008).
            if prefix_b and not field_data.lstrip().startswith(prefix_b):
                continue
            return field_data.decode("utf-8", errors="replace")

        # Variable data field with subfield.
        sub_code = spec.subfield.encode("ascii")
        for code, raw in _iter_subfields(field_data):
            if code != sub_code:
                continue
            stripped = raw.lstrip()
            if prefix_b is not None:
                if not stripped.startswith(prefix_b):
                    continue
                if spec.strip_prefix:
                    return stripped[len(prefix_b):].strip().decode(
                        "utf-8", errors="replace"
                    )
                return stripped.decode("utf-8", errors="replace").strip()
            return stripped.decode("utf-8", errors="replace").strip()

    return None


def extract_key(
    record_bytes: bytes, specs: list[FieldSpec]
) -> tuple[str, ...] | None:
    """Return the match-key tuple for a record, or None if any spec is missing.

    Catalogers usually want to OR multiple identifiers (match if any one
    matches). That's NOT what this does: callers compose match strategies by
    running multiple passes if needed. Combining specs here treats them as
    AND — the key only exists if every spec yielded a value. This is safer
    than OR (avoids false positives across heterogeneous identifiers).
    """
    parts: list[str] = []
    for spec in specs:
        value = _extract_for_spec(record_bytes, spec)
        if value is None or value == "":
            return None
        parts.append(value)
    return tuple(parts)


def _key_to_string(key: tuple[str, ...]) -> str:
    return "|".join(key)


# ---------------------------------------------------------------------------
# Record fingerprinting (for change detection)
# ---------------------------------------------------------------------------


DEFAULT_EXCLUDE_TAGS = frozenset({"001", "005"})


def fingerprint_record(
    record_bytes: bytes, exclude_tags: frozenset[str] | set[str] | None = None
) -> str:
    """SHA-256 over a canonical form of the record's content.

    Canonical form: each non-excluded field rendered as `<tag>:<raw_bytes>`,
    sorted by tag then by raw bytes. Excluding the volatile fields (defaults
    to `001` and `005`) ensures that the same bibliographic record fingerprints
    identically across vendor batches.
    """
    excl = exclude_tags if exclude_tags is not None else DEFAULT_EXCLUDE_TAGS
    excl_b = {t.encode("ascii") for t in excl}
    parts: list[bytes] = []
    for tag, length, start in _iter_directory(record_bytes):
        if tag in excl_b:
            continue
        data = _field_bytes(record_bytes, length, start)
        parts.append(tag + b":" + data)
    parts.sort()
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
        h.update(b"\x1d")  # delimiter unlikely to appear in field bytes
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Buffer iteration
# ---------------------------------------------------------------------------


def _iter_records(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield (offset, record_bytes) over a MARC blob."""
    pos = 0
    n = len(data)
    while pos < n:
        if pos + 5 > n:
            raise ValueError(f"Truncated MARC blob at offset {pos}")
        length = int(data[pos:pos + 5])
        if length < LEADER_LEN:
            # A real MARC record is at least a 24-byte leader. A length of 0
            # (or anything below the leader) would leave ``pos`` unchanged and
            # spin this loop forever — a CPU DoS reachable from any uploaded
            # .mrc. Treat it as malformed, like a truncated record. (TASK-072)
            raise ValueError(
                f"Invalid MARC record length {length} at offset {pos}: "
                f"below the {LEADER_LEN}-byte leader minimum"
            )
        if pos + length > n:
            raise ValueError(
                f"Short read at offset {pos}: expected {length} bytes, "
                f"only {n - pos} remaining"
            )
        yield pos, data[pos:pos + length]
        pos += length


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def index_buffer(name: str, data: bytes, specs: list[FieldSpec]) -> IndexResult:
    """Walk an in-memory MARC blob and index records by the given specs."""
    offsets: dict[str, int] = {}
    missing: list[int] = []
    seen_to_offsets: dict[str, list[int]] = {}
    total = 0

    for offset, record in _iter_records(data):
        key = extract_key(record, specs)
        if key is None:
            missing.append(offset)
            offsets[f"__nokey__::{offset}"] = offset
        else:
            ks = _key_to_string(key)
            if ks in offsets:
                seen_to_offsets.setdefault(ks, [offsets[ks]]).append(offset)
            else:
                offsets[ks] = offset
        total += 1

    return IndexResult(
        offsets=offsets,
        missing_key_offsets=missing,
        duplicate_offsets=seen_to_offsets,
        total_records=total,
    )


def index_buffers(
    buffers: list[tuple[str, bytes]], specs: list[FieldSpec]
) -> MultiIndexResult:
    """Index multiple (name, bytes) buffers into a combined map.

    Synthetic ``__nokey__`` keys from individual buffers are re-namespaced so
    a no-key record in buffer A cannot collide with one in buffer B. Records
    whose match key already exists in another buffer are recorded as
    cross-buffer duplicates (all occurrences, not just the secondaries).
    """
    locations: dict[str, tuple[str, int]] = {}
    per_buffer: list[tuple[str, IndexResult]] = []
    cross_dupes: dict[str, list[tuple[str, int]]] = {}

    for name, data in buffers:
        result = index_buffer(name, data, specs)
        per_buffer.append((name, result))
        for key, off in result.offsets.items():
            if key.startswith("__nokey__::"):
                ns_key = f"__nokey__::{name}::{off}"
                locations[ns_key] = (name, off)
                continue
            if key in locations:
                # Initialize cross-buffer dup list with the first occurrence
                # if this is the first time we've seen a second occurrence.
                if key not in cross_dupes:
                    cross_dupes[key] = [locations[key]]
                cross_dupes[key].append((name, off))
            else:
                locations[key] = (name, off)

    return MultiIndexResult(
        locations=locations,
        per_buffer=per_buffer,
        cross_buffer_duplicate_locations=cross_dupes,
    )


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


def compute_diff(old: MultiIndexResult, new: MultiIndexResult) -> DiffResult:
    old_ids = old.ids()
    new_ids = new.ids()
    return DiffResult(
        adds_ids=new_ids - old_ids,
        deletes_ids=old_ids - new_ids,
        common_ids=old_ids & new_ids,
    )


def sample_matches(
    old_buffers: list[tuple[str, bytes]],
    new_buffers: list[tuple[str, bytes]],
    specs: list[FieldSpec],
    limit: int = 20,
) -> list[tuple[str, tuple[str, int], tuple[str, int]]]:
    """Find up to `limit` records present on both sides under the given specs.

    Used to preview real matches before running the full diff. The order of
    returned keys is sorted for stable display. Synthetic ``__nokey__`` keys
    are skipped (those are never real matches).
    """
    old_idx = index_buffers(old_buffers, specs)
    new_idx = index_buffers(new_buffers, specs)
    common = sorted(
        k for k in old_idx.ids() & new_idx.ids() if not k.startswith("__nokey__::")
    )
    out: list[tuple[str, tuple[str, int], tuple[str, int]]] = []
    for key in common[:limit]:
        out.append((key, old_idx.locations[key], new_idx.locations[key]))
    return out


DiffStatus = Literal["unchanged", "changed", "added", "removed"]


def render_record_lines(record_bytes: bytes) -> list[str]:
    """Render a record as one line per field (LDR + tag-prefixed data).

    Stable, line-oriented form suitable for diffing. Pymarc's __str__ is also
    line-oriented but builds a Record object first; this is a direct byte walk.
    """
    leader = record_bytes[0:LEADER_LEN].decode("utf-8", errors="replace")
    lines = [f"=LDR  {leader}"]
    for tag, length, start in _iter_directory(record_bytes):
        tag_s = tag.decode("utf-8", errors="replace")
        data = _field_bytes(record_bytes, length, start).decode(
            "utf-8", errors="replace"
        )
        lines.append(f"={tag_s}  {data}")
    return lines


def _align_lists(
    old: list[str], new: list[str]
) -> list[tuple[str, str, DiffStatus]]:
    """Aligned diff between two ordered lists of strings.

    Returns one row per output position with (old_line, new_line, status):
      ``unchanged`` — same string on both sides (matched by SequenceMatcher).
      ``changed``   — different strings paired by a replace opcode.
      ``added``     — only in new (left side empty).
      ``removed``   — only in old (right side empty).
    """
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    rows: list[tuple[str, str, DiffStatus]] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                rows.append((old[i1 + k], new[j1 + k], "unchanged"))
        elif op == "replace":
            ko, kn = i2 - i1, j2 - j1
            for k in range(max(ko, kn)):
                o = old[i1 + k] if k < ko else ""
                n = new[j1 + k] if k < kn else ""
                if not o:
                    rows.append(("", n, "added"))
                elif not n:
                    rows.append((o, "", "removed"))
                else:
                    rows.append((o, n, "changed"))
        elif op == "delete":
            for k in range(i2 - i1):
                rows.append((old[i1 + k], "", "removed"))
        elif op == "insert":
            for k in range(j2 - j1):
                rows.append(("", new[j1 + k], "added"))
    return rows


def field_diff(
    old_bytes: bytes, new_bytes: bytes
) -> list[tuple[str, str, DiffStatus]]:
    """Aligned per-field diff between two MARC records."""
    return _align_lists(render_record_lines(old_bytes), render_record_lines(new_bytes))


def value_diff(
    old_values: Iterable[str], new_values: Iterable[str]
) -> list[tuple[str, str, DiffStatus]]:
    """Aligned diff between two collections of values (deduped + sorted).

    Designed for showing what values appear in a given (tag, subfield) on
    each side of the diff. Shared values land in ``equal`` runs; values
    only in one side appear as ``removed``/``added``.
    """
    return _align_lists(sorted(set(old_values)), sorted(set(new_values)))


def detect_changes(
    old: MultiIndexResult,
    new: MultiIndexResult,
    old_sources: dict[str, bytes],
    new_sources: dict[str, bytes],
    common_ids: Iterable[str],
    exclude_tags: frozenset[str] | set[str] | None = None,
) -> set[str]:
    """Among `common_ids`, return the subset whose record content differs.

    `*_sources` maps buffer_name -> bytes. The function reads each matched
    record from each side at the offset stored in the index, fingerprints it,
    and compares.
    """
    changed: set[str] = set()
    for key in common_ids:
        o_name, o_off = old.locations[key]
        n_name, n_off = new.locations[key]
        o_data = old_sources[o_name]
        n_data = new_sources[n_name]
        o_len = int(o_data[o_off:o_off + 5])
        n_len = int(n_data[n_off:n_off + 5])
        o_fp = fingerprint_record(o_data[o_off:o_off + o_len], exclude_tags)
        n_fp = fingerprint_record(n_data[n_off:n_off + n_len], exclude_tags)
        if o_fp != n_fp:
            changed.add(key)
    return changed


# ---------------------------------------------------------------------------
# Output writing (in-memory)
# ---------------------------------------------------------------------------


def write_subset_to_bytes(
    locations: Iterable[tuple[str, int]],
    sources: dict[str, bytes],
) -> bytes:
    """Concatenate selected records into a single MARC byte string.

    Records are grouped by source buffer and ordered by offset within each
    source so each buffer is read sequentially.
    """
    by_source: dict[str, list[int]] = defaultdict(list)
    for name, off in locations:
        by_source[name].append(off)

    out = io.BytesIO()
    for name in sorted(by_source.keys()):
        data = sources[name]
        for off in sorted(by_source[name]):
            length = int(data[off:off + 5])
            out.write(data[off:off + length])
    return out.getvalue()


def write_subset_to_path(
    locations: Iterable[tuple[str, int]],
    sources: dict[str, bytes],
    output_path: Path,
) -> int:
    """Stream selected records to ``output_path`` and return bytes written."""
    by_source: dict[str, list[int]] = defaultdict(list)
    for name, off in locations:
        by_source[name].append(off)

    written = 0
    with Path(output_path).open("wb") as output:
        for name in sorted(by_source.keys()):
            data = sources[name]
            for off in sorted(by_source[name]):
                length = int(data[off:off + 5])
                chunk = data[off:off + length]
                output.write(chunk)
                written += len(chunk)
    return written


# ---------------------------------------------------------------------------
# Field discovery / suggestions
# ---------------------------------------------------------------------------


def _sample_field_index(
    buffers: list[tuple[str, bytes]], sample_size: int
) -> tuple[
    dict[tuple[str, str | None], int],          # records-seen-with-pair
    dict[tuple[str, str | None], set[str]],     # distinct values seen
    dict[tuple[str, str | None], str],          # sample value
    set[tuple[str, str | None]],                # OCLC-prefixed keys
    int,                                         # records actually scanned
]:
    """Walk a sample of records and collect per-(tag, sub) frequency + values."""
    rec_counts: Counter[tuple[str, str | None]] = Counter()
    distinct_values: dict[tuple[str, str | None], set[str]] = defaultdict(set)
    samples: dict[tuple[str, str | None], str] = {}
    oclc_keys: set[tuple[str, str | None]] = set()
    scanned = 0

    for _, data in buffers:
        for _, record in _iter_records(data):
            keys_in_record: set[tuple[str, str | None]] = set()
            for tag, length, start in _iter_directory(record):
                tag_s = tag.decode("utf-8", errors="replace")
                field_data = _field_bytes(record, length, start)
                if tag.startswith(b"00"):
                    key = (tag_s, None)
                    keys_in_record.add(key)
                    value_s = field_data.decode("utf-8", errors="replace")
                    distinct_values[key].add(value_s)
                    samples.setdefault(key, value_s[:60])
                else:
                    for code, value in _iter_subfields(field_data):
                        code_s = code.decode("utf-8", errors="replace")
                        key = (tag_s, code_s)
                        keys_in_record.add(key)
                        v_stripped = value.lstrip()
                        value_s = v_stripped.decode(
                            "utf-8", errors="replace"
                        ).strip()
                        if value_s:
                            distinct_values[key].add(value_s)
                        samples.setdefault(key, value_s[:60])
                        if (
                            tag == b"035"
                            and code == b"a"
                            and v_stripped.startswith(b"(OCoLC)")
                        ):
                            oclc_keys.add(key)
            for key in keys_in_record:
                rec_counts[key] += 1
            scanned += 1
            if scanned >= sample_size:
                break
        if scanned >= sample_size:
            break

    return rec_counts, distinct_values, samples, oclc_keys, scanned


def combined_field_suggestions(
    old_buffers: list[tuple[str, bytes]],
    new_buffers: list[tuple[str, bytes]],
    sample_size: int = 500,
) -> list[CombinedFieldSuggestion]:
    """Return per-(tag, subfield) cross-side comparison sorted by overlap then coverage."""
    old_counts, old_vals, old_samples, old_oclc, old_n = _sample_field_index(
        old_buffers, sample_size
    )
    new_counts, new_vals, new_samples, new_oclc, new_n = _sample_field_index(
        new_buffers, sample_size
    )

    keys = set(old_counts.keys()) | set(new_counts.keys())
    out: list[CombinedFieldSuggestion] = []
    for tag, sub in keys:
        old_v = old_vals.get((tag, sub), set())
        new_v = new_vals.get((tag, sub), set())
        union = old_v | new_v
        shared = old_v & new_v
        overlap = (len(shared) / len(union)) if union else 0.0
        out.append(
            CombinedFieldSuggestion(
                tag=tag,
                subfield=sub,
                old_coverage=(
                    old_counts.get((tag, sub), 0) / old_n if old_n else 0.0
                ),
                new_coverage=(
                    new_counts.get((tag, sub), 0) / new_n if new_n else 0.0
                ),
                old_distinct_values=len(old_v),
                new_distinct_values=len(new_v),
                shared_values=len(shared),
                overlap=overlap,
                sample_value=old_samples.get((tag, sub))
                or new_samples.get((tag, sub)),
                is_oclc_prefixed=(tag, sub) in old_oclc
                or (tag, sub) in new_oclc,
                old_value_set=frozenset(old_v),
                new_value_set=frozenset(new_v),
            )
        )

    # Sort by discriminating power: a field is only a useful match key if it
    # has many *distinct* values that overlap. A field with 100% overlap but
    # one distinct value is useless (every record gets the same key).
    out.sort(
        key=lambda s: (
            -s.shared_values,
            -s.overlap,
            -min(s.old_coverage, s.new_coverage),
            s.tag,
            s.subfield or "",
        )
    )
    return out


def suggest_match_fields(
    buffers: list[tuple[str, bytes]], sample_size: int = 500
) -> list[FieldSuggestion]:
    """Single-side per-(tag, subfield) frequency report.

    Useful for the simple case (one set of buffers). For cross-side overlap
    info — which is far more diagnostic for picking a match key — use
    ``combined_field_suggestions`` instead.
    """
    counts, _vals, samples, oclc_keys, scanned = _sample_field_index(
        buffers, sample_size
    )
    suggestions = [
        FieldSuggestion(
            tag=tag,
            subfield=sub,
            occurrences=cnt,
            sample_size=scanned,
            sample_value=samples.get((tag, sub)),
            is_oclc_prefixed=(tag, sub) in oclc_keys,
        )
        for (tag, sub), cnt in counts.items()
    ]
    suggestions.sort(key=lambda s: (-s.occurrences, s.tag, s.subfield or ""))
    return suggestions


# ---------------------------------------------------------------------------
# Filesystem helper (kept for tests / scripted use; the UI does not use it)
# ---------------------------------------------------------------------------


def discover_marc_files(folder: str | Path) -> list[Path]:
    """List `.mrc` files directly inside folder (non-recursive, sorted)."""
    folder = Path(folder)
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".mrc" and not p.name.startswith(".")
    )
