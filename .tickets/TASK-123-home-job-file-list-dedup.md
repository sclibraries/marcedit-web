# TASK-123 — Remove duplicate Home job file list

**Status:** Completed
**Priority:** Tier 3 — Cataloger workflow clarity
**Depends on:** TASK-122

## Title

Use one actionable file list in Home Job Workspace.

## Scope

- Remove the non-interactive dataframe from Home's **Files in this job** section.
- Keep the visible metadata catalogers need: filename, record count, upload time,
  and active/current state.
- Keep the `Load`, `Remove`, and uploader-only `Delete file` actions.

## Success Criteria

1. Home Job Workspace shows each file once.
2. The list no longer displays inactive checkbox-like controls.
3. Existing load/remove/delete actions still work.
4. Focused Home tests pass.

## Outcome

- Removed the non-interactive dataframe from Home's **Files in this job** section.
- Kept a single actionable list with filename, record count, upload timestamp,
  current/available state, and actions.
- Verification:
  - `python3 -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py -q`
    passed with `13 passed`.
  - `docker compose run --rm marcedit-web python -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py tests/test_jobs_page.py tests/test_session_restore.py tests/test_jobs.py -q`
    passed with `64 passed`.
