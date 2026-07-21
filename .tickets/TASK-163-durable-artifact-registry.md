Title: Add durable artifact identity, admission, references, and leases

Parent: TASK-162

Scope:
- Add a standalone durable-artifact entity because current
  `operation_artifacts` cannot represent a ready upload before an operation.
  Store an opaque UUID identity, normalized owner, storage-generated path,
  bounded display filename, SHA-256 checksum, bytes, MARC record count, state,
  timestamps, and expiry.
- Add ordered operation-artifact references with operation id, artifact id,
  role, side, and zero-based ordinal. TASK-165 uses `old`/`new` input sides and
  ordered `adds`/`deletes` result roles; TASK-157 may add operation-specific
  roles without changing artifact ownership.
- Define states `reserved`, `pending`, `ready`, `deleting`, `deleted`, and
  `rejected`. Only `ready` artifacts may acquire new references or leases.
- Add owner-bound idempotency tokens so a lost upload-commit response can be
  recovered without creating a duplicate artifact.
- Add renewable leases for active upload, worker read, and download use.
  Cleanup transactionally changes an expired artifact with no pinning operation
  reference or live lease to `deleting`; no new consumer can race that claim.
- Operation references remain as historical metadata after terminal states but
  block cleanup only while queued, running, or cancelling. Completed result
  artifacts remain downloadable until their own expiry; completed input
  references and all failed/cancelled references cease pinning immediately.
  Cleanup retains the artifact row in `deleted` state so operation history
  remains intelligible.
- Reserve bytes transactionally before upload. Enforce validated configuration
  with these defaults: `MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS_PER_USER=2`,
  `MARCEDIT_WEB_DURABLE_MAX_ACTIVE_UPLOADS=8`,
  `MARCEDIT_WEB_DURABLE_MAX_PENDING_BYTES_PER_USER=4294967296`,
  `MARCEDIT_WEB_DURABLE_MAX_RETAINED_BYTES_PER_USER=8589934592`,
  `MARCEDIT_WEB_DIFF_MAX_INPUT_BYTES=4294967296`,
  `MARCEDIT_WEB_DURABLE_MAX_FILE_BYTES=2147483648`, and
  `MARCEDIT_WEB_DIFF_MAX_OUTPUT_BYTES=4294967296`. Production must explicitly
  configure `MARCEDIT_WEB_DURABLE_MAX_TOTAL_BYTES` and
  `MARCEDIT_WEB_DURABLE_MIN_FREE_BYTES`; preflight fails if either is absent,
  invalid, or nonpositive.
- Release reservations on rejection/expiry and calculate replacements by byte
  delta. A capacity loss during streaming fails closed before publication.
- Migrate additively without changing current TASK-156 saved-task artifacts.

Success Criteria:
- Admission is atomic under concurrent users and cannot exceed per-user,
  operation, service-wide, or free-disk reservations.
- An idempotency retry after commit returns the same authorized artifact; a
  token owned by another user reveals nothing.
- Reference and lease acquisition loses deterministically to a cleanup claim,
  and cleanup loses deterministically to an existing reference/lease.
- Terminal operation references retain audit linkage without preventing the
  documented 30-day artifact expiry.
- Job adoption copies bytes into immutable Job-version storage; Job versions do
  not point into expiring artifact storage.
- Migration, lifecycle transitions, authorization, reservation rollback,
  concurrent admission, low-disk behavior, crash-released reservations, and
  cleanup races have intent-focused tests.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
