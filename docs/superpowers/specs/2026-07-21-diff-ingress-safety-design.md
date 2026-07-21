# TASK-134/TASK-162 Diff Ingress Safety Design

Tickets:
[TASK-134](../../../.tickets/TASK-134-diff-uploader-widget-memory.md) and
[TASK-162](../../../.tickets/TASK-162-durable-large-file-ingress.md)

Date: 2026-07-21

## Goal

Prevent large Diff workflows from destabilizing the shared Streamlit service
while preserving 2 GiB as the private large-MARC product target. Ship a narrow
uploader-retention fix first, then move browser ingress, Diff processing,
retained output, and downloads onto a durable artifact boundary whose memory
use does not scale with file size.

## Current Constraint

Streamlit's `file_uploader` receives the complete request body before
application code can copy it to disk. TASK-134 can release the widget sooner,
but it cannot reduce that peak. The private service unit has
`MemoryHigh=1536M` and `MemoryMax=2G`; a legitimate 2 GiB upload plus normal
process memory can terminate every session.

TASK-156 begins after one input is durable and currently completes with one
result and same-file Job versioning. It does not provide pre-operation artifact
identity, ordered inputs, atomic multiple results, or bounded HTTP transfer.

## Selected Architecture

The private browser talks through Apache/Shibboleth to a loopback artifact
service. That service reserves storage, streams upload/download bodies in fixed
chunks, and owns artifact lifecycle. Streamlit receives only opaque IDs and
bounded metadata. Queue operations acquire durable references and renewable
leases; the worker processes immutable files and publishes results through a
fenced multi-result transaction.

Queue-after-Streamlit-upload was rejected because it keeps the dangerous
ingress peak. A separate high-memory Streamlit Diff service was rejected because
it still buffers whole bodies and duplicates deployment without creating the
artifact contract needed by merge and split.

## Delivery Decomposition

TASK-162 is the parent acceptance gate, not one implementation unit:

1. **TASK-163** adds artifact identity, storage reservations, ordered operation
   references, lifecycle states, idempotency, and consumer leases.
2. **TASK-164** adds the authenticated streaming upload service, Apache/Compose/
   systemd deployment, and production-safe request boundary.
3. **TASK-165** moves Diff to the queue and adds fenced ordered-input and atomic
   multi-result publication primitives.
4. **TASK-166** streams downloads outside Streamlit and implements retention and
   crash reconciliation.
5. **TASK-162** closes only after the children and end-to-end production
   acceptance pass.

TASK-147 measures that final browser path. TASK-157 reuses TASK-163/165
cardinality primitives and adds merge/split-specific sibling Job publication
and reversal.

## TASK-134 Containment

Both Diff widgets rotate after every nonempty ingest round, including
rejected-only rounds. Staged entries persist independently of widget state.
Each accepted file writes to a fresh generated candidate and closes
successfully before staged metadata switches. Only then is the superseded path
removed. A failed replacement leaves the prior file and derived results intact.
Within one round, the last successfully written duplicate display name wins.

Distinct names always receive distinct storage paths even if sanitization would
collide. An accepted add, replacement, or removal invalidates suggestions,
previews, indices, diff results, generated blobs, and pagination. A rejected-only
round does not. Rejection state retains at most 20 entries with a 255-character
filename and 512-character reason for one post-ingest acknowledgement cycle.

Containment admits at most 1,000 staged files and the existing configured
session-byte aggregate across both sides, using replacement deltas. Physical
admission still requires the complete candidate size plus a 1 GiB configured
free-disk reserve. It adds per-file removal and recursively removes the work
tree on Start over.

Each active render holds a shared advisory work-tree lock. A sweep examines at
most 10 trees inactive for 24 hours, acquires a nonblocking exclusive lock,
rechecks staleness, atomically renames the directory into a root-confined
quarantine, and deletes without following symlinks. A reclaimed returning
session resets cleanly with a bounded notice.

TASK-134 does not claim a safe 2 GiB ingress peak and does not redesign output
downloads. Those belong to TASK-162's children.

## Durable Artifact Registry and Admission

A durable artifact exists independently of an operation. It has an opaque UUID,
canonical owner, storage-generated path, normalized bounded display filename,
SHA-256, byte and record counts, state, timestamps, and expiry. Lifecycle states
are `reserved`, `pending`, `ready`, `deleting`, `deleted`, and `rejected`.

An ordered operation reference stores artifact, role, side, and zero-based
ordinal. A consumer must transactionally acquire a reference or renewable lease
while the artifact is `ready`. Cleanup can claim only an expired artifact with
no pinning reference or live lease by atomically changing it to `deleting`; no
new consumer may acquire it afterward. References pin only while an operation
is queued/running/cancelling. Completed inputs and all failed/cancelled
references cease pinning immediately; completed results pin until their own
expiry. Historical links remain after the artifact row becomes `deleted`. Job
adoption copies bytes into immutable Job version storage rather than pointing a
Job version at expiring artifact storage.

The reservation transaction enforces validated configuration whose defaults are
two active uploads per user, eight active uploads service-wide, 4 GiB pending
bytes per user, 8 GiB retained bytes per user, 4 GiB aggregate Diff inputs,
2 GiB per artifact, and 4 GiB aggregate Diff outputs. The corresponding settings
are
`MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS_PER_USER`,
`MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS`,
`MARCEDIT_WEB_DURABLE_MAX_PENDING_BYTES_PER_USER`,
`MARCEDIT_WEB_DURABLE_MAX_RETAINED_BYTES_PER_USER`,
`MARCEDIT_WEB_DIFF_MAX_INPUT_BYTES`, `MARCEDIT_WEB_DURABLE_MAX_FILE_BYTES`, and
`MARCEDIT_WEB_DIFF_MAX_OUTPUT_BYTES`. Production preflight requires explicit
positive `MARCEDIT_WEB_DURABLE_MAX_TOTAL_BYTES` and
`MARCEDIT_WEB_DURABLE_MIN_FREE_BYTES`. Replacement charges only its positive
delta. Admission or capacity loss fails closed before publication and releases
reservations safely.

Owner-bound idempotency tokens make a lost commit response recoverable without
creating another multi-gigabyte artifact.

## Upload Request and Authentication Contract

The first release is private Shibboleth-only. The artifact service listens on
loopback and rejects direct requests without constant-time proxy attestation.
Apache's protected route strips all client identity and attestation headers,
then injects canonical Shibboleth identity and the server-only secret. Anonymous,
unapproved, forged, and public/OAuth-only requests fail closed.

State-changing requests require the exact configured Origin and a non-simple
custom header; CORS is denied. Reservation accepts JSON only. Content upload
accepts raw MARC only and requires an exact `Content-Length` matching the
reservation. Browser code never receives a proxy secret.

`POST /uploads` validates the display filename, declared bytes, and owner-bound
idempotency key before reserving. `PUT /uploads/{opaque_id}/content` reads fixed
1 MiB chunks, writes a generated pending path, enforces the exact byte count,
computes SHA-256, validates MARC/counts, and performs this durability order:

1. close and fsync the candidate file;
2. fsync the pending parent;
3. rename to a generated final path;
4. fsync the final parent; and
5. commit ready metadata.

Only committed DB state makes the file visible. A crash before commit leaves an
orphan for age-protected reconciliation. A crash after commit but before the
response is recovered with `GET /uploads/status/{idempotency_key}`.

The service accepts at most eight concurrent upload bodies with backlog 32.
Strict MARC validation rejects empty files, invalid or impossible five-byte and
leader lengths, truncated or trailing bytes, and parse failures. Validation
must consume exactly to EOF and count at least one record.

Display names are basename-only Unicode NFC metadata, stripped of controls and
bounded to 255 UTF-8 bytes. They never choose storage paths or enter response
headers without safe encoding.

The repository gains a loopback artifact systemd/Compose service, health check,
restart policy, writable roots, shared-group permissions, explicit cgroup
limits, Apache body/timeout/proxy-streaming configuration, preflight checks, and
deployment instructions.

## Queued Diff and Publication Protocol

The `marc-diff` request schema contains ordered `old` and `new` artifact IDs and
immutable match/change settings. Operation references preserve side and ordinal.
Workers acquire and renew read leases with the fenced operation lease.

Adds and deletes are written to generated staging paths. Each candidate is
validated, file- and directory-fsynced, renamed to a final generated path, and
parent-fsynced. One SQLite transaction—guarded by the current operation lease
and cancellation state—inserts every result artifact/reference and marks the
operation completed. No download endpoint reads a final path without committed
ready metadata, so zero, one, or two orphan files may exist after a crash, but a
subset is never published.

Ingress requires at least one record. Diff results have a narrower contract: a
valid no-change operation publishes both roles as zero-byte, zero-record
artifacts with SHA-256 of empty content. Empty result acceptance is role-bound
and cannot weaken upload validation.

Before processing, the worker pessimistically reserves the configured 4 GiB
aggregate output ceiling through the same service-wide byte/free-disk
transaction used by ingress. The fenced attempt owns that reservation. Unused
bytes release after publication; failure, cancellation, stale lease, and crash
recovery release the balance only after charged staging/orphan paths are gone.

If commit acknowledgement is lost, reconciliation opens a fresh connection and
checks the complete result set and terminal state before retaining or removing
any path. A stale worker or cancelled operation cannot commit. Streamlit stores
only request, progress, and result metadata.

## Direct Download and Retention

The artifact service authorizes each download and acquires a renewable lease
before opening the file. It streams fixed-size chunks, refreshes the lease, and
releases it in `finally`. Streamlit provides only the link/metadata. The first
release rejects Range requests with 416 and encodes the normalized filename via
RFC 5987 `Content-Disposition`.

Unpinned ready inputs and results expire after 30 days by default; terminal
operation links remain for history but stop pinning according to the lifecycle
rules above. Stale pending uploads expire after one hour. An expired ID returns
410 only to its former owner and reveals nothing to another user. Cleanup
transactionally
claims `deleting`, then performs root-confined symlink-safe unlink and finalizes
state. Reconciliation retries interrupted reservation, pending, final-file,
unlink, and DB transitions idempotently. Bounded audit events record accepted,
rejected, expired, and reconciled outcomes without secrets.

## Testing and Production Acceptance

TASK-134 tests rotation, rejected-only/mixed rounds, accumulation, equal-size
and failed replacement, duplicate names, sanitization collisions, invalidation,
admission deltas, removal, reset cleanup, and bounded abandoned-tree sweeping.

TASK-163 through TASK-166 add scaled tests for concurrent reservation,
low-disk/capacity loss, idempotency, reference/cleanup races, proxy bypass and
header forgery, Origin/CORS enforcement, cross-user access, exact length and
filename boundaries, disconnects around commit, checksum/count integrity,
every multi-result rename/fsync/commit crash point, lease fencing, cancellation,
direct-download memory, expiry, and reconciliation. Tests fail if a body enters
Streamlit state.

Production acceptance uses checked-in fixed-seed fixture manifests and records
the deployed SHA, exact bytes/records/checksums and expected Diff outputs,
synchronized three-session timing, every service cgroup, aggregate host memory
and disk, watchdog restarts, operation events, and output integrity. It requires
zero OOM, watchdog restart, skipped record, checksum mismatch, integrity error,
or silent test skip. The exact 2 GiB run occurs only after ITS confirms the host
envelope; otherwise TASK-162 stays open with the measured supported ceiling.

## Non-Goals

- TASK-134 does not replace Streamlit ingress or promise safe 2 GiB uploads.
- Public/OAuth-only large ingress is not supported in the first release.
- Resumable multipart upload, cloud object storage, checksum deduplication,
  Range downloads, and user-configurable retention are deferred.
- TASK-162 does not implement merge/split sibling Job publication or reversal;
  TASK-157 consumes the generalized artifact and operation primitives.
