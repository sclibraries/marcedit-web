Title: Stream durable artifact downloads and reconcile retention

Parent: TASK-162
Dependency: TASK-163, TASK-164, TASK-165

Scope:
- Add an authenticated authorization-checked download route to the artifact
  service so response bodies never pass through Streamlit.
- Add the final Diff result links and expired-result presentation to Streamlit;
  UI state contains URLs and bounded metadata only.
- Gate activation with TASK-165: deploy and verify upload, analysis, review,
  publication, and download together before disabling the legacy synchronous
  Diff path. `MARCEDIT_WEB_DURABLE_DIFF_ENABLED=false` is the single gate and
  enables the complete path only after preflight confirms ingress, worker,
  review, and download health. Neither child may expose a production state
  where Diff results cannot be retrieved.
- Acquire a renewable download lease transactionally before opening a ready
  artifact; refresh while streaming and release in `finally`. Cleanup may claim
  only expired artifacts with no pinning references or live leases.
- Stream fixed-size chunks with bounded RSS. The first release rejects Range
  requests with 416 and serves the complete artifact only. Encode the normalized
  display filename safely with RFC 5987 `Content-Disposition`; never interpolate
  raw control characters into headers.
- Default unpinned ready-input and result retention to 30 days. Expired IDs
  return a bounded 410 to their former owner and reveal nothing to other users.
- Reconcile pending files after one hour only when they have no live renewable
  upload lease; a slow active upload is never stale solely because of age.
  Reconcile expired ready artifacts and every `cleanup-pending` superseded,
  published, abandoned, or expired Diff workflow profile/index/review/staging
  generation; also reconcile orphan final files, `deleting` rows interrupted
  before/after unlink, and abandoned reservations. Claim in SQLite before
  root-confined symlink-safe unlink. Release charged bytes only after successful
  unlink, then record bounded audit events for expiry and reconciliation.
- Never delete artifacts pinned by queued/running/cancelling operations or held
  by worker/download leases. Immutable Job versions use independent paths.
- Add one dedicated singleton reconciler service as the sole periodic owner,
  configured by `MARCEDIT_WEB_RECONCILE_INTERVAL_SECONDS=60` (10-3600).
  Compose/systemd deploy exactly one instance and preflight rejects a missing or
  invalid interval. Ingress may clean only its own immediately failed partial;
  Streamlit, workers, and request handlers do not run periodic sweeps.

Success Criteria:
- Download RSS remains chunk-bounded at the configured maximum artifact size
  and Streamlit receives only link/metadata state.
- Direct download supports generated Diff results through the configured 8 GiB
  per-result ceiling; the 2 GiB browser-upload ceiling does not apply to worker
  outputs.
- Cleanup races with submission, worker reads, downloads, expiry, and Job
  adoption are deterministic and covered by adversarial tests.
- Reconciliation is idempotent across every unlink/commit crash boundary and
  cannot traverse outside the artifact root or follow symlinks.
- Superseded-review and post-publication workspace cleanup is recovered across
  metadata-switch, cleanup-claim, unlink, and accounting-release crash points.
- Service/deployment tests prove only the dedicated reconciler owns the
  periodic loop; duplicate transactional cleanup claims remain harmless.
- Authorization, 410/404 distinction, Range rejection, filename encoding,
  retention configuration, lease renewal/expiry, and audit bounds are tested.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
