# TASK-126 — Home job files table redesign

**Status:** In-Progress
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
