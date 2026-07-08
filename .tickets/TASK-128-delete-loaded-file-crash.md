# TASK-128 — Deleting the loaded file crashes the session

**Status:** Completed
**Priority:** Tier 1 — Production crash in cataloger flow
**Depends on:** TASK-120, TASK-126

## Title

Detach the session's loaded batch when its backing upload file is deleted.

## Problem

Clicking **Delete file permanently** on the upload that is currently loaded
in the session raises
`FileNotFoundError: data/uploads/<user>/<file>.mrc` on the next render.

Root cause (traced 2026-07-08): `jobs.remove_upload(delete_file=True)`
unlinks the file, but the delete handlers on Home and the Jobs page leave
`st.session_state["store"]` pointing at the deleted path. `has_upload()`
stays truthy (`store.count()` is cached metadata), so Home's "Loaded batch"
footer calls `current_raw_bytes()` → `RecordStore.to_mrc_bytes()` →
`iter_records()` → `path.open("rb")` → crash. Both delete call sites
(`00_Home.py`, `B_Jobs.py`) have the bug. Soft "Remove from job" is
unaffected — it keeps the file on disk.

## Scope

- New helper `session.detach_loaded_batch(file_path)`: when the current
  store is backed by `file_path`, reset the loaded-batch keys (`store`,
  `issues_cache`, `editor_text`, `editor_dirty`) — the same set
  `load_persisted_upload` writes.
- Call it from both delete handlers (Home and B_Jobs) after a successful
  `remove_upload(..., delete_file=True)`, before `st.rerun()`.
- Defense in depth: `current_raw_bytes()` returns `None` on
  `FileNotFoundError` so a dangling store from paths we cannot reach
  (e.g. a collaborator's session holding a file another user deleted)
  degrades to "no download" instead of a crash page.

## Out of scope

- Cross-session resilience on other pages (View/Editor iterating a store
  whose file a collaborator deleted) — follow-up candidate.

## Success Criteria

1. Failing-first tests: deleting the loaded upload clears the loaded batch;
   deleting a different upload leaves it alone; `current_raw_bytes()`
   returns `None` when the backing file is missing.
2. Home and B_Jobs delete handlers both detach the loaded batch (page-level
   tests click the delete button and assert the store is cleared).
3. Focused suites pass locally and in Docker (same command set as
   TASK-126/127).

## Outcome

- Added `session.detach_loaded_batch(file_path)` and called it from both
  delete handlers (`00_Home.py`, `B_Jobs.py`) after successful
  `remove_upload(..., delete_file=True)`, before `st.rerun()`.
- `current_raw_bytes()` now returns `None` on `FileNotFoundError`
  (collaborator-deleted shared file).
- Verification:
  - RED: 5 new tests failed first for the intended reasons
    (AttributeError missing helper ×2, FileNotFoundError, store not
    cleared, detach not called).
  - GREEN local: `python3 -m pytest tests/test_session_restore.py
    tests/test_home_page_jobs.py tests/test_app_pages.py
    tests/test_jobs_page.py tests/test_jobs.py -q` → 73 passed.
  - GREEN Docker (Python 3.9 / Streamlit 1.50): same five files →
    73 passed.
- Code review: ready to merge, no Critical/Important findings. Two
  pre-existing minor observations logged for follow-up consideration:
  `current_raw_bytes` can't distinguish deleted-file from misconfigured
  uploads root, and `remove_upload` marks the DB row removed before
  unlinking (a non-FileNotFoundError unlink failure leaves a
  partially-deleted state).
