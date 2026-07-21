Title: Release Diff page uploader widget memory after ingest

Related: TASK-117, TASK-130, TASK-131, TASK-132, TASK-162

Scope:
- Apply the Home uploader key-rotation pattern to both multi-file Diff
  uploaders so accepted Streamlit upload objects are released after each
  ingest round.
- Treat this as short-term containment only. Streamlit still buffers each
  incoming file before application code runs, so this ticket does not make a
  2 GiB upload safe under a 2 GiB service memory ceiling. TASK-162 owns the
  bounded-memory durable-ingress design.
- Persist staged-file metadata independently of the uploader widgets and merge
  successful files across upload rounds.
- Write an accepted upload to a fresh collision-resistant temporary path,
  flush and close it successfully, then switch staged metadata and delete the
  superseded path. A short write, disk-full error, or other ingest failure keeps
  the prior logical entry and derived results intact, removes the partial, and
  records a bounded rejection.
- Give every staged file a collision-resistant disk path separate from its
  user-facing filename. Re-uploading the same user-facing filename replaces
  that logical entry and deletes its superseded staged file; distinct names
  that sanitize to the same basename remain distinct.
- Invalidate cached suggestions, preview matches, completed diff indices,
  generated output blobs, and associated pagination whenever an accepted file
  is added, replaced, or removed. A round containing only rejections does not
  invalidate valid results.
- Rotate after every nonempty round, including rejected-only and mixed rounds,
  and release every upload object. Retain at most 20 rejection entries with
  filenames bounded to 255 characters and reasons bounded to 512 characters;
  present that summary for one post-ingest acknowledgement cycle.
- Reject admission beyond 1,000 staged files total or the existing
  `MARCEDIT_WEB_MAX_SESSION_BYTES` aggregate across both sides. Replacement
  logical quota charges only the positive byte delta, but physical admission
  requires free space for the complete new candidate plus
  `MARCEDIT_WEB_DIFF_MIN_FREE_BYTES` (default 1 GiB). Never delete the old file
  until the new candidate is accepted.
- Add per-file removal from the staged list. "Start over" closes active
  mappings, recursively deletes the complete Diff work directory, and resets
  only Diff state.
- Reconcile at most 10 abandoned `marcedit-web-diff-*` work trees per page
  render when their activity marker is older than 24 hours. Each active render
  holds a shared advisory lock. A sweeper must acquire a nonblocking exclusive
  lock, recheck staleness, and atomically rename the directory into a
  root-confined quarantine before symlink-safe deletion. If a returning
  session's directory was reclaimed, reset its Diff state with a bounded
  user-facing notice.
- Keep generated adds/deletes byte blobs unchanged in this containment ticket;
  TASK-162 moves those outputs to retained disk artifacts.

Success Criteria:
- After every ingest round, both uploader widgets release accepted upload
  objects and staged metadata retains all accepted files from prior rounds.
- Equal-size, different-content replacement writes the new bytes, removes the
  superseded path, and invalidates every result derived from the old content.
- Filename sanitization collisions cannot overwrite or alias another logical
  file.
- Mixed accepted/rejected rounds rotate the widget, retain accepted files, and
  show each rejection exactly once from persisted bounded state.
- Rejected-only rounds rotate and release their objects without changing valid
  staged files or derived results.
- Duplicate display names in one round resolve deterministically in upload
  order: the last successfully written occurrence becomes the logical entry,
  and every superseded candidate is removed.
- File-count and staged-byte admission is deterministic under replacement,
  rejection, and disk-full failures, including same-size replacement without
  enough physical candidate headroom.
- Users can remove one staged file; its path is deleted and dependent Diff
  state is invalidated without removing unrelated files.
- "Start over" removes the session work tree rather than only forgetting its
  path.
- Intent-focused tests fail before and pass after for rotation, accumulation,
  equal-size and failed replacement, duplicate names, collisions, invalidation,
  mixed and rejected-only rounds, admission limits, per-file removal, recursive
  reset cleanup, and concurrent active-render/abandoned-workdir reconciliation.
- Focused and complete test suites pass with every skip reported, and code
  review has no unresolved Critical or Important findings.

Status: Todo (requirements revised 2026-07-21 after cross-ticket review)
