Title: Add durable artifact identity, admission, references, and leases

Parent: TASK-162

Scope:
- Add a standalone durable-artifact entity because current
  `operation_artifacts` cannot represent a ready upload before an operation.
  Store an opaque UUID identity, normalized owner, storage-generated path,
  bounded display filename, SHA-256 checksum, bytes, MARC record count, state,
  structural-validation status, cached immutable pymarc-validation outcome,
  validator-policy version, timestamps, and expiry. A structurally ready
  artifact remains downloadable if later full parsing fails, but cannot acquire
  a new Diff workflow reference.
- Add ordered operation-artifact references with operation id, artifact id,
  role, side, and zero-based ordinal. TASK-165 uses `old`/`new` input sides and
  ordered `adds`/`deletes` result roles; TASK-157 may add operation-specific
  roles without changing artifact ownership.
- Define states `reserved`, `pending`, `ready`, `deleting`, `deleted`, and
  `rejected`. General operation/read/download references and leases require
  `ready`. Upload is the exception: the first content PUT atomically performs
  `reserved` to `pending` and acquires an exclusive fenced upload-attempt token
  with a renewable lease. A second PUT while that lease is live cannot open a
  second writer and returns the existing bounded status. Cleanup can claim
  `pending` only after both its age threshold and upload lease have expired.
- Bind each idempotency token to the canonical owner, normalized display
  filename, declared byte count, and request kind so a lost upload-commit
  response can be recovered without returning an artifact for different
  request metadata. A retry with the same token and different bound metadata
  fails deterministically.
- Add renewable leases for active upload, worker read, and download use.
  Cleanup transactionally changes an expired artifact with no pinning operation
  reference or live lease to `deleting`; no new consumer can race that claim.
- Operation references remain as historical metadata after terminal states but
  block cleanup only while queued, running, or cancelling, except that a
  completed Diff profile holds explicit review-dependency references to its
  sources until the workflow is published, abandoned, or expires. Completed
  result artifacts remain downloadable until their own expiry; other completed
  input references and all failed/cancelled references cease pinning
  immediately.
  Cleanup retains the artifact row in `deleted` state so operation history
  remains intelligible.
- Add a durable owner-bound Diff workflow root. Its states are `open`,
  `publishing`, `published`, `abandoned`, and `expired`; it owns one immutable
  profile, at most one current completed analysis, source review dependencies,
  and the 16 GiB analysis-workspace reservation. Only a fenced
  `open -> publishing` claim may select an analysis for publication. The result
  visibility transaction also moves the workflow to `published` and releases
  source dependencies. Failure recovery may return the same fenced attempt to
  `open` only after its output staging is reconciled. No new analysis or publish
  starts after a terminal state.
- Reserve bytes transactionally before upload. Enforce validated configuration
  with these defaults: `MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS_PER_USER=2`,
  `MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS=8`,
  `MARCEDIT_WEB_DURABLE_MAX_PENDING_BYTES_PER_USER=4294967296`,
  `MARCEDIT_WEB_DURABLE_MAX_RETAINED_BYTES_PER_USER=34359738368`,
  `MARCEDIT_WEB_DURABLE_MAX_UPLOAD_BYTES=2147483648`,
  `MARCEDIT_WEB_DIFF_MAX_INPUT_BYTES=8589934592`,
  `MARCEDIT_WEB_DIFF_MAX_ANALYSIS_BYTES=17179869184`,
  `MARCEDIT_WEB_DIFF_MAX_RESULT_BYTES=8589934592`, and
  `MARCEDIT_WEB_DIFF_MAX_OUTPUT_BYTES=8589934592`. The upload limit applies to
  each browser-provided source; the input/output limits apply to each Diff
  operation aggregate; the analysis limit reserves disk-backed profile, index,
  and review workspace; and the result limit applies to each generated output.
  Ready sources/results count against the 32 GiB retained-per-user ceiling,
  while analysis workspace is charged separately against its fenced operation,
  the service total, and free-disk reserve. Production must explicitly configure
  `MARCEDIT_WEB_DURABLE_MAX_TOTAL_BYTES` and
  `MARCEDIT_WEB_DURABLE_MIN_FREE_BYTES`; preflight fails if either is absent,
  invalid, or nonpositive.
- Release reservations on rejection/expiry and calculate replacements by byte
  delta. A capacity loss during streaming fails closed before publication.
- Migrate additively without changing current TASK-156 saved-task artifacts.
- Use the repository's shared SQLite connection policy in every Streamlit,
  ingress, worker, and reconciler process: WAL mode, an explicit validated busy
  timeout, and short transactions. Never hold a writer transaction across body
  streaming, MARC validation, hashing, fsync, rename, or other file work.
- Add validated shared settings:
  `MARCEDIT_WEB_SQLITE_BUSY_TIMEOUT_MS=5000` (100-60000),
  `MARCEDIT_WEB_ARTIFACT_RETENTION_SECONDS=2592000` and
  `MARCEDIT_WEB_DIFF_REVIEW_RETENTION_SECONDS=2592000` (3600-31536000),
  `MARCEDIT_WEB_UPLOAD_PENDING_TTL_SECONDS=3600` (300-86400),
  `MARCEDIT_WEB_UPLOAD_LEASE_SECONDS=120` and
  `MARCEDIT_WEB_ARTIFACT_READ_LEASE_SECONDS=120` (30-600). Pending TTL must be
  at least twice the upload lease. Invalid or inconsistent production values
  fail preflight rather than silently falling back.

Success Criteria:
- Admission is atomic under concurrent users and cannot exceed per-user,
  operation, service-wide, or free-disk reservations.
- An idempotency retry after commit returns the same authorized artifact; a
  token owned by another user reveals nothing, and changed bound metadata is
  rejected rather than returning the prior artifact.
- Reference and lease acquisition loses deterministically to a cleanup claim,
  and cleanup loses deterministically to an existing reference/lease.
- Concurrent content PUTs cannot create two writers; the fenced pending-upload
  claim, live-lease behavior, expired-attempt cleanup, and idempotent status
  recovery are covered by adversarial tests.
- Terminal operation references retain audit linkage without preventing the
  documented 30-day artifact expiry.
- A completed, reviewable Diff profile keeps its source artifacts available
  through bounded review expiry/publication; releasing that dependency makes
  them eligible for normal retention cleanup.
- Full pymarc validation outcome is cached against immutable artifact content;
  invalid content cannot enter Diff review. Reuse requires the current
  code-defined validator-policy version; an older outcome is revalidated.
  Compare-and-swap publication makes concurrent validators for the same
  artifact/version converge without contradictory outcomes.
- Concurrent analysis/publish/expiry attempts obey the workflow state machine;
  source dependencies release only in the all-results publication transaction
  or a fenced abandon/expiry transition.
- Job adoption copies bytes into immutable Job-version storage; Job versions do
  not point into expiring artifact storage.
- Migration, lifecycle transitions, authorization, reservation rollback,
  concurrent admission, low-disk behavior, crash-released reservations, and
  cleanup races have intent-focused tests.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
