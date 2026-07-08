# TASK-129 — Shared job files table on Home and Jobs pages

**Status:** In-Progress
**Priority:** Tier 3 — Cataloger workflow clarity
**Depends on:** TASK-126, TASK-127, TASK-128

## Title

Extract the TASK-126 job files table into a shared renderer and use it on
both Home and the Jobs detail page.

## Problem

The Jobs detail page (`/Jobs`) still shows the pre-TASK-126 layout — worse,
it renders the file list twice: a read-only `st.dataframe` (Filename,
Records, Size, Uploaded, Active) followed by paragraph-style rows with
wrapped Load/Remove/Delete buttons. Home and Jobs have already drifted once
(delete label, layout); duplicated layout code is how that happens.

User decision (2026-07-08): one shared table on both pages, with a Size
column added everywhere.

## Scope

- New `marcedit_web/render/job_files.py`:
  - `format_size(num_bytes)` (moved from `B_Jobs._format_size`),
  - `format_uploaded_at(value)` (moved from `00_Home._format_uploaded_at`),
  - `render_job_files_table(uploads, *, user, role, key_prefix)` — the
    TASK-126 bordered 7-column grid (Filename | Records | Size | Uploaded |
    Status | Load | ⋮) with the popover action menu, permission gates,
    TASK-127 load semantics, and TASK-128 detach-on-delete.
- Home `_render_job_uploads` becomes a thin wrapper: fetch uploads,
  subheader + empty caption, delegate with `key_prefix="home_job_upload"`.
- Jobs detail Files section: drop the duplicate dataframe and the old
  action rows; delegate with `key_prefix="job_upload"`. Delete label gains
  parity ("Delete file permanently").
- Widget keys unchanged on both pages
  (`home_job_upload_{load,remove,delete}_{id}`,
  `job_upload_{load,remove,delete}_{id}`).
- Page-specific empty-state captions stay in the pages.

## Success Criteria

1. Both pages render the identical table layout via the shared renderer;
   Home gains a Size column; Jobs loses the duplicate dataframe.
2. All existing behavior pins keep passing with unchanged widget keys:
   load-switch (TASK-127), detach-on-delete (TASK-128), permission gating
   (Remove: owner/editor; Delete: uploader only; viewer: Load only, no ⋮).
3. Failing-first tests cover: Size column on Home, Jobs table replacing the
   dataframe + old rows, Jobs delete label parity, shared helpers.
4. Focused suites pass locally and in Docker; visual spot-check of the Jobs
   page shows the new table.
