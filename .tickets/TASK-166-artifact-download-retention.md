Title: Stream durable artifact downloads and reconcile retention

Parent: TASK-162
Dependency: TASK-163, TASK-164, TASK-165

Scope:
- Add an authenticated authorization-checked download route to the artifact
  service so response bodies never pass through Streamlit.
- Add the final Diff result links and expired-result presentation to Streamlit;
  UI state contains URLs and bounded metadata only.
- Acquire a renewable download lease transactionally before opening a ready
  artifact; refresh while streaming and release in `finally`. Cleanup may claim
  only expired artifacts with no pinning references or live leases.
- Stream fixed-size chunks with bounded RSS. The first release rejects Range
  requests with 416 and serves the complete artifact only. Encode the normalized
  display filename safely with RFC 5987 `Content-Disposition`; never interpolate
  raw control characters into headers.
- Default unpinned ready-input and result retention to 30 days. Expired IDs
  return a bounded 410 to their former owner and reveal nothing to other users.
- Reconcile stale pending files after one hour, expired ready artifacts, orphan
  final files, `deleting` rows interrupted before/after unlink, and abandoned
  reservations. Claim in SQLite before root-confined symlink-safe unlink; record
  bounded audit events for expiry and reconciliation.
- Never delete artifacts pinned by queued/running/cancelling operations or held
  by worker/download leases. Immutable Job versions use independent paths.

Success Criteria:
- Download RSS remains chunk-bounded at the configured maximum artifact size
  and Streamlit receives only link/metadata state.
- Cleanup races with submission, worker reads, downloads, expiry, and Job
  adoption are deterministic and covered by adversarial tests.
- Reconciliation is idempotent across every unlink/commit crash boundary and
  cannot traverse outside the artifact root or follow symlinks.
- Authorization, 410/404 distinction, Range rejection, filename encoding,
  retention configuration, lease renewal/expiry, and audit bounds are tested.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
