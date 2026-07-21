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
3. **TASK-165** moves Diff analysis and publication to the queue, preserves the
   interactive review workflow through bounded durable review artifacts, and
   adds fenced ordered-input and atomic multi-result publication primitives.
4. **TASK-166** streams downloads outside Streamlit and implements retention and
   crash reconciliation.
5. **TASK-162** closes only after the children and end-to-end production
   acceptance pass.

TASK-147 may close on its non-Diff Home/quick/saved-task production evidence;
TASK-162 owns final Diff browser-path acceptance. TASK-157 reuses TASK-163/165
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

Containment admits at most 1,000 staged files and 8 GiB across both sides via
`MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES`, using replacement deltas. This explicitly
reintroduces a containment-only total staged-disk ceiling, not the removed
per-side aggregate cap. The 8 GiB default leaves 4 GiB headroom above the
canonical 2 GiB old plus 2 GiB new full-dump workflow. Each source remains
subject to the existing 2 GiB `MARCEDIT_WEB_MAX_DIFF_BYTES` limit. Physical
admission still requires the complete replacement candidate plus a 1 GiB
configured free-disk reserve. It adds per-file removal and recursively removes
the work tree on Start over.

TASK-134 does not add an abandoned-tree sweeper. Correctly distinguishing an
active Streamlit session would require advisory-lock and quarantine machinery
that TASK-164/165 removes at cutover. During the containment window, abandoned
trees may persist until the private temporary namespace or service restarts;
this temporary disk-leak tradeoff is documented rather than hidden.

TASK-134 does not claim a safe 2 GiB ingress peak and does not redesign output
downloads. Those belong to TASK-162's children.

## Durable Artifact Registry and Admission

A durable artifact exists independently of an operation. It has an opaque UUID,
canonical owner, storage-generated path, normalized bounded display filename,
SHA-256, byte and structural record counts, structural-validation status, cached
immutable pymarc-validation outcome plus validator-policy version, state,
timestamps, and expiry. Lifecycle
states are `reserved`, `pending`, `ready`, `deleting`, `deleted`, and `rejected`.
A structurally ready upload remains owner-downloadable if later full parsing
fails, but it cannot acquire a new Diff workflow reference. Concurrent full
validators for the same artifact/policy version converge through
compare-and-swap publication. A code-defined validator-policy version—not an
environment judgment—changes when parsing validity semantics change; older
cached outcomes are revalidated before reuse.

An ordered operation reference stores artifact, role, side, and zero-based
ordinal. General operation, read, and download references/leases require
`ready`. Upload is the exception: the first content PUT atomically changes
`reserved` to `pending` and acquires an exclusive fenced upload-attempt token
with a renewable lease. A second PUT cannot create another writer while that
lease is live and receives the existing bounded status. Cleanup can claim
`pending` only after both its age threshold and upload lease expire. Cleanup can
claim a ready expired artifact only when it has no pinning reference or live
lease, atomically changing it to `deleting`; no new consumer may acquire it
afterward. References pin only while an operation
is queued/running/cancelling. Completed inputs and all failed/cancelled
references cease pinning immediately, except a completed Diff profile holds
explicit review-dependency references to its sources until publication,
abandonment, or the normal 30-day review expiry. Completed results pin until
their own expiry. Historical links remain after the artifact row becomes
`deleted`. Job
adoption copies bytes into immutable Job version storage rather than pointing a
Job version at expiring artifact storage.

A durable owner-bound Diff workflow root owns one immutable profile, at most one
current completed analysis, the source review dependencies, and the 16 GiB
analysis-workspace reservation. Its states are `open`, `publishing`,
`published`, `abandoned`, and `expired`. Only a fenced `open` to `publishing`
claim may select an analysis for output. The all-results visibility transaction
also makes the workflow `published` and releases its source dependencies.
Failure recovery returns the same fenced attempt to `open` only after output
staging is reconciled. Terminal workflows reject new analysis or publish work.

The reservation transaction enforces validated configuration whose defaults are
two active uploads per user, eight active uploads service-wide, 4 GiB pending
bytes per user, 32 GiB retained bytes per user, 2 GiB per browser-uploaded
artifact, 8 GiB aggregate Diff inputs, 16 GiB analysis workspace, 8 GiB per
generated Diff result, and 8 GiB aggregate Diff outputs. Thirty-two retained
GiB permits one maximum Diff's 8 GiB of ready inputs and 8 GiB of ready outputs
to coexist with equal per-user headroom. Analysis workspace is charged
separately to its fenced operation and the service/free-disk totals. The
corresponding settings are
`MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS_PER_USER`,
`MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS`,
`MARCEDIT_WEB_DURABLE_MAX_PENDING_BYTES_PER_USER`,
`MARCEDIT_WEB_DURABLE_MAX_RETAINED_BYTES_PER_USER`,
`MARCEDIT_WEB_DURABLE_MAX_UPLOAD_BYTES`,
`MARCEDIT_WEB_DIFF_MAX_INPUT_BYTES`, `MARCEDIT_WEB_DIFF_MAX_ANALYSIS_BYTES`,
`MARCEDIT_WEB_DIFF_MAX_RESULT_BYTES`, and
`MARCEDIT_WEB_DIFF_MAX_OUTPUT_BYTES`. Production preflight requires explicit
positive `MARCEDIT_WEB_DURABLE_MAX_TOTAL_BYTES` and
`MARCEDIT_WEB_DURABLE_MIN_FREE_BYTES`. Replacement charges only its positive
delta. Admission or capacity loss fails closed before publication and releases
reservations safely.

Idempotency tokens bind canonical owner, normalized filename, declared bytes,
and request kind. A lost commit response is recoverable without creating
another multi-gigabyte artifact, while reuse with changed bound metadata fails
instead of returning the wrong artifact.

All Streamlit, ingress, worker, and reconciler processes use the repository's
shared SQLite connection policy: WAL mode, an explicit validated busy timeout,
and short transactions. Streaming, parsing, hashing, fsync, rename, and other
file work never occur while holding the SQLite writer lock.

Shared operational settings are validated consistently in every process:
`MARCEDIT_WEB_SQLITE_BUSY_TIMEOUT_MS=5000` (100-60000),
`MARCEDIT_WEB_ARTIFACT_RETENTION_SECONDS=2592000` and
`MARCEDIT_WEB_DIFF_REVIEW_RETENTION_SECONDS=2592000` (3600-31536000),
`MARCEDIT_WEB_UPLOAD_PENDING_TTL_SECONDS=3600` (300-86400), and
`MARCEDIT_WEB_UPLOAD_LEASE_SECONDS=120` plus
`MARCEDIT_WEB_ARTIFACT_READ_LEASE_SECONDS=120` (30-600). Pending TTL must be at
least twice the upload lease. Missing required production values, invalid
ranges, and inconsistent relationships fail preflight.

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
Production requires `MARCEDIT_WEB_ARTIFACT_ORIGIN` as exactly one normalized
HTTPS origin with no path, query, or fragment.

The browser upload surface is a small same-origin page served by the artifact
service through its Shibboleth-protected Apache route. It passes the native
File/Blob as the raw request body, allowing the browser to provide its length,
and is not a sandboxed Streamlit component or cross-origin iframe. Streamlit
links to the page and polls bounded
artifact metadata for the authenticated owner. This preserves Shibboleth
cookies and exact-Origin enforcement by construction.

`POST /uploads` validates the display filename, declared bytes, and owner-bound
idempotency key before reserving. `PUT /uploads/{opaque_id}/content` reads fixed
1 MiB chunks, writes a generated pending path, enforces the exact byte count,
computes SHA-256, renews the upload lease, performs an incremental cheap
structural MARC length-walk/count, and follows this durability order:

1. close and fsync the candidate file;
2. fsync the pending parent;
3. rename to a generated final path;
4. fsync the final parent; and
5. commit ready metadata.

All request-body, validation, and filesystem work finishes before the short
ready-metadata transaction. Only committed DB state makes the file visible. A
crash before commit leaves an orphan for age-protected reconciliation. A crash
after commit but before the response is recovered with
`GET /uploads/status/{idempotency_key}`.

The service accepts at most eight concurrent upload bodies with backlog 32.
Synchronous structural validation rejects empty files, invalid or impossible
five-byte and leader lengths, truncated or trailing bytes, and a walk that does
not consume exactly to EOF and count at least one record. Full per-record pymarc
parsing is deferred to queued Diff profiling, where any parse failure prevents
review publication and caches the artifact's immutable validation outcome.
Apache and client timeouts cover bounded transfer time, not
minutes of worker CPU parsing on an open upload connection.

Display names are basename-only Unicode NFC metadata, stripped of controls and
bounded to 255 UTF-8 bytes. They never choose storage paths or enter response
headers without safe encoding.

The repository gains a loopback artifact systemd/Compose service, health check,
restart policy, writable roots, shared-group permissions, explicit cgroup
limits, Apache body/timeout/proxy-streaming configuration, preflight checks, and
deployment instructions.

The protected artifact route alone uses Apache `LimitRequestBody 0`; the
application rejects missing, chunked, mismatched, or greater-than-2-GiB content
length before reading the body. This avoids Apache's own boundary rejecting the
valid exact 2,147,483,648-byte case while leaving the application as the strict
limit authority. Apache proxies the request body without buffering it into
Streamlit or an intermediate application allocation.

## Queued Diff Review and Publication Protocol

Diff uses three versioned operation kinds. `marc-diff-profile` contains ordered
`old` and `new` artifact IDs. The worker fully parses the records and creates
field suggestions, source record locations, and reusable disk-backed profile
data before the user selects match/change settings. `marc-diff-analysis`
references that immutable profile plus the selected settings and produces
durable bounded or paginated counts, missing/duplicate-key groups, changed
keys, and other review metadata. A settings change starts a new analysis from
the profile without re-uploading or repeating structural validation.
Review-dependency references keep sources pinned until workflow publication,
abandonment, or the normal 30-day review expiry. Field suggestions retain the
current first-500-record behavior; key groups return at most 100 keys per page;
record-slice responses return at most 20 records and 2 MiB. Authorized review
endpoints acquire short read leases. Streamlit never mmaps complete sources or
stores file bodies in session state.

Only one completed setting-dependent review set is current per profile. A new
analysis atomically switches current-generation metadata after success and
marks the prior paths `cleanup-pending`; failure or cancellation leaves the
prior review usable. Root-confined unlink happens outside the writer
transaction, and charged bytes release only after successful unlink. This keeps
repeated settings changes inside the single workflow workspace reservation.

Profile and analysis linkage is persisted under the workflow root. Analyses
start only while it is `open`; the fenced transition selects exactly one for
publication, and dependencies release only with all committed results or a
fenced abandon/expiry transition.

After the user reviews warnings and changed records,
`marc-diff-publish` references the immutable analysis and records the reviewed
`include_changes` choice before generating outputs. This preserves the current
steps 3–6 and prevents output generation from forcing a choice before review.
Operation references preserve side and ordinal. Workers acquire and renew read
leases with the fenced operation lease.

Indexes must be disk-backed rather than Python dictionaries/sets whose memory
scales with record cardinality. Before profiling, the worker pessimistically
reserves 16 GiB once for the workflow's disk-backed profile, index, and review
workspace. Those
paths remain charged until publication, abandonment, or expiry removes them. A
maximum-supported-input, high-cardinality run must keep every worker phase below
1 GiB RSS, leaving headroom below the 1536 MiB worker MemoryHigh. The first
release fixes `MARCEDIT_WEB_DIFF_WORKER_CONCURRENCY=1`; profile, analysis, and
publish use bounded batches/caches and never mmap or materialize a complete
source. Acceptance measures both phase-process RSS and aggregate worker-cgroup
memory under competing queued work.

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

Before publication, the worker pessimistically reserves the configured 8 GiB
aggregate output ceiling through the same service-wide byte/free-disk
transaction used by ingress. The fenced attempt owns that reservation. Unused
bytes release after publication; failure, cancellation, stale lease, and crash
recovery release the balance only after charged staging/orphan paths are gone.

The all-results transaction also marks the workflow profile/index/review
workspace `cleanup-pending`. After commit, root-confined unlink runs outside
SQLite and releases charged bytes only after success. The singleton reconciler
recovers superseded-review and published-workflow cleanup across metadata
switch, claim, unlink, and accounting-release crash boundaries; abandoned and
expired workflows use the same protocol.

Each generated result is limited to 8 GiB even though each browser-uploaded
source is limited to 2 GiB. If commit acknowledgement is lost, reconciliation
opens a fresh connection and checks the complete result set and terminal state
before retaining or removing
any path. A stale worker or cancelled operation cannot commit. Streamlit stores
only request, progress, bounded review, and result metadata.

TASK-165 and TASK-166 have one production cutover gate. A single
`MARCEDIT_WEB_DURABLE_DIFF_ENABLED=false` gate is enabled only after ingress,
worker, review, and download health preflight succeeds. The legacy synchronous
Diff path remains enabled until same-origin upload, queued analysis/review,
queued publication, and direct result download are deployed and verified
together. The system never enables a queued Diff path whose outputs users
cannot retrieve.

## Direct Download and Retention

The artifact service authorizes each download and acquires a renewable lease
before opening the file. It streams fixed-size chunks, refreshes the lease, and
releases it in `finally`. Streamlit provides only the link/metadata. The first
release rejects Range requests with 416 and encodes the normalized filename via
RFC 5987 `Content-Disposition`.

Unpinned ready inputs and results expire after 30 days by default; terminal
operation links remain for history but stop pinning according to the lifecycle
rules above. Review expiry is measured from workflow/profile creation and is
not extended by repeated analyses. Pending uploads older than one hour are
eligible only if no live
renewable upload lease exists; an active slow transfer is not stale by age
alone. An expired ID returns
410 only to its former owner and reveals nothing to another user. Cleanup
transactionally
claims `deleting`, then performs root-confined symlink-safe unlink and finalizes
state. One dedicated singleton reconciler service is the sole periodic owner,
using `MARCEDIT_WEB_RECONCILE_INTERVAL_SECONDS=60` (10-3600). Compose/systemd
deploy one instance. Ingress cleans only its own immediate failed partial;
Streamlit, workers, and request handlers do not sweep. Reconciliation retries interrupted
reservation, pending, final-file, unlink, and DB transitions idempotently.
Bounded audit events record accepted,
rejected, expired, and reconciled outcomes without secrets.

## Testing and Production Acceptance

TASK-134 tests rotation, rejected-only/mixed rounds, accumulation, equal-size
and failed replacement, duplicate names, sanitization collisions, invalidation,
admission deltas, removal, reset cleanup, and the documented absence of implicit
abandoned-tree deletion.

TASK-163 through TASK-166 add scaled tests for concurrent reservation,
low-disk/capacity loss, idempotency, reference/cleanup races, proxy bypass and
header forgery, Origin/CORS enforcement, cross-user access, exact length and
filename boundaries, disconnects around commit, checksum/count integrity,
every multi-result rename/fsync/commit crash point, lease fencing, cancellation,
high-cardinality disk-index worker RSS, bounded/paginated review and record-slice
authorization, joint cutover, direct-download memory through an 8 GiB result,
exclusive pending-upload attempts, workflow-state races,
expiry-without-live-upload-lease, and single-owner reconciliation. A protected
Apache-route integration accepts exactly 2,147,483,648 bytes and rejects the
next byte before reading its body. Tests fail if a body enters Streamlit state.

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
