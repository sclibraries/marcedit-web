Title: Queue Diff with ordered inputs and atomic multiple results

Parent: TASK-162
Dependency: TASK-163, TASK-164

Scope:
- Add a versioned `marc-diff` operation kind without weakening existing
  `saved-task-run` requests.
- Submit ordered `old` and `new` artifact references with explicit zero-based
  ordinals plus immutable match/change settings. The worker reads only leased
  ready artifacts and renews leases with its operation lease.
- Generalize completion to publish ordered multiple results. Adds and deletes
  candidates use storage-generated staging names; each is validated, file- and
  parent-fsynced, renamed into final storage, and parent-fsynced before one
  SQLite transaction inserts every result reference and marks the fenced
  operation completed.
- Ingress artifacts must contain at least one MARC record, but a valid no-change
  Diff publishes both result roles as zero-byte, zero-record artifacts with the
  SHA-256 of empty content. Result validation accepts empty files only for those
  explicit Diff output roles; it never weakens ingress validation.
- Before processing, pessimistically reserve the configured 4 GiB aggregate
  Diff-output maximum through TASK-163's service-wide byte/free-disk
  transaction. Persist the reservation against the fenced attempt, release
  unused bytes after publication, and release the full reservation on every
  failure, cancellation, stale-lease, and reconciled-crash path. Staging files
  and unreferenced orphans remain charged until removed.
- Define publication solely by committed DB state. No endpoint can read a final
  path without a committed ready artifact/reference. If filesystem work
  succeeds but commit acknowledgement is lost, reconciliation checks fresh DB
  state before retaining or deleting either candidate.
- Cancellation and stale leases cannot commit. Failed/cancelled operations
  expose neither output, and reconciliation handles every crash boundary
  without publishing a subset.
- Replace synchronous Diff execution and session-state output blobs with queue
  submission, progress/history, and retained result metadata. TASK-166 owns the
  final direct-download links and expired-result presentation.

Success Criteria:
- Input side/order survives restarts and output ordering is deterministic.
- Both result references and terminal state become visible together, or none do.
- A no-change Diff publishes deterministic empty adds and deletes artifacts.
- Tests inject crashes before/after each rename, fsync, DB commit, and response;
  verify lease fencing, cancellation races, lost acknowledgement, orphan
  reconciliation, concurrent output reservations, low-disk/capacity loss,
  exact counts/checksums, and no partial publication.
- Streamlit session state contains only bounded request/result metadata and no
  input or output file body.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
