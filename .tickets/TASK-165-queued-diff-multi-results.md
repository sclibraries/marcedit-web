Title: Queue Diff review with ordered inputs and atomic multiple results

Parent: TASK-162
Dependency: TASK-163, TASK-164

Scope:
- Add separate versioned `marc-diff-profile`, `marc-diff-analysis`, and
  `marc-diff-publish` operation kinds without weakening existing
  `saved-task-run` requests. Profile accepts ordered `old` and `new` artifact
  references, fully validates them, and produces field suggestions before the
  user selects match/change settings. Analysis references the immutable profile
  plus those settings. Publish references the completed analysis and the user's
  reviewed `include_changes` decision.
- Preserve the current interactive Diff workflow: bounded match-field
  suggestions, missing- and duplicate-key groups with record dialogs, changed
  counts and side-by-side records, then the include-changed-records choice
  before output generation. Analysis publishes durable bounded/paginated review
  metadata and disk-backed key/record-location indexes. Profiling produces
  field suggestions and source record locations; analysis produces the
  setting-dependent match, warning, count, and changed-record review.
  Suggestions retain the current first-500-record behavior; key groups return
  at most 100 keys per page; record-slice responses return at most 20 records
  and 2 MiB. Authorized review APIs acquire short read leases;
  Streamlit never mmaps a complete source or stores source/output body bytes in
  session state. Review-dependency references keep sources pinned only until
  workflow publication, abandonment, or the normal 30-day review expiry.
- Keep at most one completed analysis review set per profile. A successful new
  analysis atomically switches the current review-generation metadata and marks
  prior setting-dependent paths `cleanup-pending`; a failed/cancelled
  replacement leaves the prior review usable. Root-confined unlink happens
  outside the writer transaction, and charged bytes release only after unlink.
- Persist profile and analysis linkage under TASK-163's Diff workflow root.
  Analysis is allowed only while the root is `open`; a single fenced transition
  selects one analysis for `publishing`; the result commit closes the workflow
  and releases source dependencies atomically.
- Submit ordered artifact references with explicit zero-based ordinals plus
  immutable settings. The worker reads only leased ready artifacts and renews
  leases with its operation lease. Full per-record pymarc validation occurs in
  profiling, caches the immutable artifact's outcome with a code-defined
  validator-policy version, and fails before field suggestions or other review
  publication. A current-version cached invalid artifact cannot start another
  Diff profile; an older policy version triggers compare-and-swap revalidation.
- Replace in-memory all-record key dictionaries/sets with disk-backed indexes.
  Pessimistically reserve the configured 16 GiB profile/index/review workspace
  once per workflow before profiling, charge staging and durable review paths until workflow
  publication/abandonment/expiry removes them, and fail closed on capacity
  loss. At the maximum supported input aggregate, each worker phase's peak RSS
  must stay below 1 GiB, leaving headroom beneath the 1536 MiB worker
  MemoryHigh.
- Set `MARCEDIT_WEB_DIFF_WORKER_CONCURRENCY=1` as the only supported first-release
  value. Profile, analysis, and publish use bounded batches/caches and may not
  mmap or materialize a complete source. Test both per-process RSS and aggregate
  worker cgroup memory under queued competing work.
- Generalize completion to publish ordered multiple results. Adds and deletes
  candidates use storage-generated staging names; each is validated, file- and
  parent-fsynced, renamed into final storage, and parent-fsynced before one
  SQLite transaction inserts every result reference and marks the fenced
  operation completed.
- Ingress artifacts must contain at least one MARC record, but a valid no-change
  Diff publishes both result roles as zero-byte, zero-record artifacts with the
  SHA-256 of empty content. Result validation accepts empty files only for those
  explicit Diff output roles; it never weakens ingress validation.
- Before publish processing, pessimistically reserve the configured 8 GiB
  aggregate Diff-output maximum through TASK-163's service-wide byte/free-disk
  transaction. Persist the reservation against the fenced attempt, release
  unused bytes after publication, and release the full reservation on every
  failure, cancellation, stale-lease, and reconciled-crash path. Staging files
  and unreferenced orphans remain charged until removed.
- Define publication solely by committed DB state. No endpoint can read a final
  path without a committed ready artifact/reference. If filesystem work
  succeeds but commit acknowledgement is lost, reconciliation checks fresh DB
  state before retaining or deleting either candidate.
- The all-results transaction also marks the workflow's profile/index/review
  workspace `cleanup-pending`. Unlink occurs after commit outside SQLite and
  releases its charged bytes only after success; crash recovery delegates any
  remaining paths to TASK-166's singleton reconciler.
- Cancellation and stale leases cannot commit. Failed/cancelled operations
  expose neither output, and reconciliation handles every crash boundary
  without publishing a subset.
- Replace synchronous Diff execution and session-state output blobs with queue
  submission, progress/history, bounded review state, and retained result
  metadata. Keep the legacy synchronous Diff path enabled until TASK-166 is
  deployed and the joint queued-upload/review/publish/download path passes its
  release gate; TASK-165 must not strand users without result retrieval.
- Name that gate `MARCEDIT_WEB_DURABLE_DIFF_ENABLED`; it defaults false and
  production preflight refuses to enable it unless ingress, worker, review, and
  download health checks all pass.

Success Criteria:
- Input side/order survives restarts and output ordering is deterministic.
- Existing suggestions, key warnings/dialogs, changed-record side-by-side
  review, and the pre-publication include-changes decision remain available
  from bounded or paginated durable review data.
- Suggestions are available before match/change settings are submitted; a
  settings change can create a new analysis from the immutable profile without
  re-uploading or rescanning the sources for structural validity.
- Both result references and terminal state become visible together, or none do.
- A no-change Diff publishes deterministic empty adds and deletes artifacts.
- Tests inject crashes before/after each rename, fsync, DB commit, and response;
  verify lease fencing, cancellation races, lost acknowledgement, orphan
  reconciliation, concurrent output reservations, low-disk/capacity loss,
  exact counts/checksums, and no partial publication.
- Streamlit session state contains only bounded request, review, and result
  metadata and no input or output file body.
- Every maximum-size profile, analysis, and publish phase satisfies the
  documented sub-1-GiB process RSS bound and the aggregate worker-cgroup bound;
  tests use high-cardinality match keys that would expose an in-memory index.
- Tests inject crashes around review-generation metadata switch, old-generation
  unlink/accounting release, publication cleanup marking, and post-publication
  workspace unlink/accounting release.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
