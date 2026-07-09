# TASK-124 — Home job file selectable table

**Status:** Completed
**Priority:** Tier 3 — Cataloger workflow clarity
**Depends on:** TASK-123

## Title

Use a selectable table for Home Job Workspace files.

## Scope

- Replace the paragraph-style Home job file rows with a selectable dataframe.
- Use a text `Status` column instead of non-actionable boolean checkboxes.
- Show actions for the selected file only.
- Preserve load, soft-remove, and uploader-only hard-delete behavior.

## Success Criteria

1. Home Job Workspace renders files in one table.
2. The table has no checkbox-like Active column.
3. Selecting a row exposes the correct actions for that file.
4. Focused Home and Docker tests pass.

## Outcome

- Replaced paragraph-style file rows with one selectable table.
- Replaced the boolean `Active` display with a text `Status` column.
- Action buttons now apply to the selected table row only.
- Verification:
  - `python3 -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py -q`
    passed with `13 passed`.
  - `docker compose run --rm marcedit-web python -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py tests/test_jobs_page.py tests/test_session_restore.py tests/test_jobs.py -q`
    passed with `64 passed`.
