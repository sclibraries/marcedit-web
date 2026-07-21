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
- Reject admission beyond 200 staged files total or
  `MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES` across both sides (default 8 GiB /
  8,589,934,592 bytes). This deliberately adds a containment-only total
  staged-disk ceiling; it does not restore the removed per-side aggregate cap.
  The 200-file bound leaves descriptor headroom for the existing render path,
  which opens a file handle and mmap for every staged file, under the service's
  expected 1,024-descriptor limit.
  The 8 GiB default leaves 4 GiB of headroom above the canonical 2 GiB old plus
  2 GiB new full-dump workflow. Each uploaded file remains subject to the
  existing 2 GiB `MARCEDIT_WEB_MAX_DIFF_BYTES` limit. Replacement logical quota
  charges only the positive byte delta, but physical admission requires free
  space for the complete new candidate plus
  `MARCEDIT_WEB_DIFF_MIN_FREE_BYTES` (default 1 GiB). Never delete the old file
  until the new candidate is accepted.
- Add per-file removal from the staged list. "Start over" closes active
  mappings, recursively deletes the complete Diff work directory, and resets
  only Diff state.
- Do not add an in-app abandoned-tree sweeper. Safely distinguishing an active
  Streamlit session from an abandoned one requires synchronization machinery
  that TASK-164/165 will promptly remove. For this containment window,
  abandoned work trees may remain until the private temporary namespace or
  service is restarted; "Start over" remains the explicit in-session cleanup.
  Record this temporary disk-leak tradeoff in deployment notes and remove the
  staging path entirely at durable-ingress cutover.
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
  reset cleanup, and the documented absence of implicit abandoned-tree
  deletion.
- Focused and complete test suites pass with every skip reported, and code
  review has no unresolved Critical or Important findings.

Status: Todo (requirements revised 2026-07-21 after cross-ticket review)
