# ADR: Shared Job Collaboration and Locking Model

**Status:** Accepted for TASK-085 design; implementation deferred to TASK-086.
**Date:** 2026-06-25
**Related tickets:** TASK-081, TASK-082, TASK-083, TASK-085, TASK-086

## Context

marcedit-web now has the foundations needed for controlled collaboration:

- `jobs` and `job_access` define owner/editor/viewer access for job-scoped
  work.
- `job_snapshots` records per-change before/after provenance.
- `advisory_locks` provides atomic SQLite locks with holder and expiry.
- SQLite runs in WAL mode with connection-per-call access and explicit
  `BEGIN IMMEDIATE` transactions for shared-state swaps.

The collaboration goal is not real-time multi-user editing. The target is
safe shared project work where one cataloger can check out a record or batch
operation, other catalogers see the lock, and no one silently overwrites another
person's work.

## Decision

Use a hybrid check-out model:

1. **Record-level locks for normal cataloging edits.**
   Inline record edits and structured fixed-field edits lock one record at a
   time. Other users can view the record but cannot save changes until the lock
   is released or expires.
2. **Job-level locks for batch-wide mutations.**
   Full MARC editor saves, task runs, imports, restores, and any future
   operation that rewrites the loaded batch acquire a job-level lock. A
   job-level lock blocks record-level saves for that job while it is held.
3. **No real-time co-editing.**
   The system shows lock and presence state, but does not merge simultaneous
   edits or stream keystrokes between users.

This gives catalogers useful concurrency for routine per-record work while
preserving a simple safety boundary around operations that can change the whole
batch.

## Lock Keys

Use the existing advisory lock table with these resource keys:

- `resource_type = "job"`, `resource_id = "<job_id>"` for batch-wide locks.
- `resource_type = "record"`, `resource_id = "<job_id>:<record_index>"`
  for single-record locks.

Record index is 1-based in the user interface and should be stored 1-based in
the lock key so audit and UI messages match what catalogers see.

Before acquiring a record lock, TASK-086 must check for an active job lock. A
job lock can only be acquired when no active record locks exist for that job.
That cross-resource check must be done in the same immediate SQLite
transaction as lock acquisition.

## Roles and Access

The initial collaboration UI should enforce:

- `owner`: manage job sharing, acquire/release locks, restore snapshots, and
  force-release expired or abandoned locks.
- `editor`: acquire/release locks and save edits.
- `viewer`: view records, run validation, and inspect provenance, but not save
  changes or acquire edit locks.

Admin users may force-release locks for support and recovery. Manual SQLite
edits are not a supported approval or recovery path.

## Expiry, Renewal, and Stealing

Locks are leases, not permanent ownership.

- Default TTL: 15 minutes for record locks, 30 minutes for job locks.
- The holder renews a lock on active edit/save page reruns.
- Expired locks are treated as unavailable to the old holder and acquirable by
  another editor.
- If a lock expires while the original holder still has an edit buffer open,
  Save must re-check ownership and fail loud instead of writing.
- Force-release is explicit, audited, and limited to owner/admin. The UI should
  say who held the lock and when it expired before offering force-release.

There is no silent lock steal for normal editors in the first implementation.
That keeps the lost-update story simple and auditable.

## Lost-Update Prevention

Saving requires both conditions:

1. The current user still holds the required lock.
2. The data being saved is based on the same snapshot/version observed when
   editing began.

TASK-086 should add a lightweight version token for the loaded job state. A
snapshot id, upload row update timestamp, or explicit job revision column are
acceptable as long as save can compare "opened from version X" with "current
version is still X". If the version changed, Save is blocked and the cataloger
must reload the record.

Every accepted mutation creates a `job_snapshots` row so rollback and "who
changed what" remain queryable.

## Presence and UX

Presence is advisory and lightweight:

- Show who currently has the job open, based on recent heartbeat/rerun activity.
- Show lock holder, lock scope, and expiry near edit controls.
- Non-holders see locked edit controls as disabled/read-only, with the holder
  email and expiry time.
- Viewers should still be able to inspect records and validation warnings.
- When a lock is released or expires, the next Streamlit rerun reflects the
  updated state. No websocket-style live update is required beyond normal
  Streamlit reruns.

Presence must not be used as authorization. `job_access` and lock ownership are
the authorization checks.

## Streamlit and SQLite Mapping

Streamlit reruns the page script frequently and serves users from one process.
The implementation should treat every button click/save as a fresh server-side
action:

- Read current identity from the trusted session accessor.
- Check `job_access`.
- Acquire or renew the required lock with an immediate SQLite transaction.
- Re-check lock ownership and version token immediately before save.
- Write the mutation and provenance snapshot.
- Release the lock when the user clicks Done/Cancel or when the lease expires.

The database remains the synchronization boundary. In-memory session state is
only a draft/edit buffer and cannot be trusted for authorization or conflict
resolution.

## Scale Ceiling and Re-Architecture Trigger

The chosen substrate is acceptable for the expected Five College scale of about
15-20 concurrent catalogers using one Streamlit process and SQLite WAL.

Stay on SQLite while:

- Writes are short transactions.
- Batch-wide job locks are occasional.
- Lock contention is visible but rare.
- The app runs as a single Streamlit service process.

Re-architect to Postgres or another server database, and likely a multi-process
application model, when any of these become true:

- More than 20-30 concurrent active catalogers are expected.
- Multiple app processes/hosts need to serve the same database.
- Users routinely encounter database locked/write timeout errors.
- Presence needs near-real-time updates rather than rerun-based refresh.
- Batch-wide operations become frequent enough to block normal record editing.

MariaDB/Postgres was deliberately avoided for the first collaboration version
because it adds operational complexity before the workload requires it.

## Consequences

Benefits:

- Enables useful concurrent cataloging without real-time merge complexity.
- Keeps lost-update prevention explicit and testable.
- Builds directly on TASK-081, TASK-082, and TASK-083.
- Preserves the current operational model until scale requires a larger
  database architecture.

Costs:

- Batch-wide operations block per-record editing while held.
- Expired edit buffers may fail on save, requiring reload.
- TASK-086 must add cross-resource lock checks and version tokens; the existing
  `advisory_locks` primitive alone is not enough for the full UX.

## TASK-086 Implementation Notes

TASK-086 should be split into focused sub-tickets:

1. Access-list UI on top of `job_access`.
2. Lock/version service helpers for job and record scopes.
3. Record edit checkout/read-only UI.
4. Job-level lock integration for full-batch operations.
5. Presence heartbeat and lock-holder display.
6. Provenance display for job snapshots.

Each implementation ticket must include concurrent tests for lock acquisition,
expired lock handling, lost-update blocking, and role enforcement.
