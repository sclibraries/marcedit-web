# TASK-126 — Home job files table redesign

**Status:** Completed
**Priority:** Tier 3 — Cataloger workflow clarity
**Depends on:** TASK-125
**Spec:** docs/superpowers/specs/2026-07-08-home-job-files-table-design.md (local)

## Title

Make the Home job files list read as a table: Load button + ⋮ action menu per row.

## Scope

- Replace the nested action sub-columns in `_render_job_uploads` with a
  6-column single-line grid (`vertical_alignment="center"`) inside a
  bordered container with a styled header row.
- Per row: one Load button plus one ⋮ popover containing "Remove from job"
  (owner/editor) and "Delete file permanently" (uploader only), each with an
  explanatory caption. No ⋮ renders when the viewer has neither permission.
- Display-only formatting: thousands-separated record counts, human-readable
  upload timestamps, colored Current/Available status.
- No behavior changes: same widget keys, same callbacks, same permission
  gates, same error/rerun handling.

## Success Criteria

1. Every file renders as one single-height row; no button label wraps.
2. Load / Remove / Delete target the correct upload id (existing tests).
3. Remove appears only for owner/editor; Delete only for the uploader; a
   viewer row shows Load and no ⋮ menu.
4. `_format_uploaded_at` renders ISO-8601 UTC as e.g. `Jul 1, 2026 09:14`
   and falls back to the raw string on parse failure.
5. Focused local suite and the Docker suite pass.

## Outcome

### Implementations

**Layout replacement:** `_render_job_uploads` now renders a bordered container with a 6-column centered grid (`_UPLOADS_GRID = [4, 1, 2, 1.4, 1, 0.6]`). Header row uses bold markdown labels; data rows show Filename, Records (thousands-separated), Uploaded (human-readable), Status (colored), Load button, and ⋮ popover (gated to users with remove or delete permission).

**Popover action menu:** When the user has permission to remove or delete, a ⋮ button renders a popover containing:
- "Remove from job" (`home_job_upload_remove_{id}`, caption: owner/editor only)
- "Delete file permanently" (`home_job_upload_delete_{id}`, caption: uploader only)

No popover renders for viewers.

**Formatting helpers:** Added `_format_uploaded_at(value) -> str` to convert ISO-8601 UTC timestamps to human-readable format (e.g., "Jul 1, 2026 09:14"), with fallback to raw string on parse failure.

### Verification Commands & Results

**Local test suite (TDD):**
- RED: `python3 -m pytest tests/test_home_page_jobs.py -q` → `3 failed, 8 passed`
- GREEN: `python3 -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py -q` → `15 passed, 62 warnings in 0.25s`

**Docker suite:**
- `docker compose run --rm marcedit-web python -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py tests/test_jobs_page.py tests/test_session_restore.py tests/test_jobs.py -q` → `66 passed in 1.58s`

All tests pass; 62 warnings are pre-existing `DeprecationWarning`s from unrelated modules (db.py, jobs.py, upload_persistence.py).

### Visual Spot-Check

Controller performed deferred visual spot-check with a seeded job at the app's real `layout="wide"`: single-height rows confirmed, no wrapped button labels, ⋮ popover renders Remove/Delete with permission gating confirmed live.

### Files Changed

- `marcedit_web/views/00_Home.py`
- `tests/test_home_page_jobs.py`

Commit: `0d3add5 feat: redesign home job files table with load and action menu`
