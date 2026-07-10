# Large-Batch Memory and Performance Design

**Ticket:** [TASK-147](../../../.tickets/TASK-147-large-batch-memory-performance.md)

## Goal

Keep View, single-record editing, and synchronous batch processing responsive
for 50K-100K MARC records while 3-5 catalogers share a Red Hat Streamlit
service capped at 2 GB.

## Storage And Interactive Access

`RecordStore` remains the source of truth. It gains direct live-index lookup,
using a compact mapping from live positions to raw file locations, so `get(n)`
parses only record `n`. Replacements, deletions, and appends update that
mapping without changing iteration order. A monotonic revision identifies the
exact in-session content generation. Reindexing uses mmap instead of loading
the backing file into bytes.

View navigation uses integer arithmetic for an unfiltered batch. Search may
scan the batch once for a new query, then retains only matching indices keyed
by query and store revision. Prev, Next, and record jumps reuse those results.
Single-record editing keeps only one parsed record/draft in session state.

## Batch Data Flow

Batch boundaries exchange paths and compact metadata. Sandbox output, diffs,
previews, exports, and provenance snapshots must not return or retain an
entire MRC byte string or a list of all parsed records. Preview stores counts,
capped examples, artifact paths, and the source revision. Apply rejects a
stale revision, streams the full result to a temporary file, validates it,
copies before/after snapshot files disk-to-disk, and atomically adopts the
result into the current store.

Full before/after snapshot files remain the rollback contract. Their creation
is bounded-memory, and stale preview/run directories are explicitly cleaned
when replaced or invalidated.

## Production Guardrails

A process-wide gate admits two heavy operations by default, configurable with
`MARCEDIT_WEB_MAX_CONCURRENT_BATCHES`. Waiting sessions do not start another
sandbox child. Structured performance logging records operation, phase,
records, bytes, elapsed time, outcome, and normalized peak RSS.

The private systemd unit keeps `MemoryMax=2G`, adds `MemoryHigh=1536M`, and
uses `MemorySwapMax=0` only on cgroup v2. Deployment documentation includes
the Red Hat preflight, cgroup observation, concurrent smoke test, and stale
temporary-file maintenance.

## Acceptance Criteria

- Record 100,000 lookup is independent of position and under 250 ms on the
  production benchmark host.
- A standard 100K quick operation completes under 30 seconds.
- Three simultaneous large sessions remain below 1.5 GB cgroup memory.
- No whole-batch bytes or record lists survive in Streamlit session state.
- No OOM, watchdog restart, skipped record, or silent cleanup failure occurs.

SQLite record storage, background jobs, and changes to the MARC/user workflow
are intentionally out of scope.
