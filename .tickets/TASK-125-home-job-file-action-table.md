# TASK-125 — Home job file action table

**Status:** Completed
**Priority:** Tier 3 — Cataloger workflow clarity
**Depends on:** TASK-124

## Title

Put Home job file actions in table columns.

## Scope

- Replace the selected-row action bar with a table-like row layout.
- Keep file metadata and actions on the same row.
- Avoid non-interactive dataframe checkbox columns.
- Preserve load, soft-remove, and uploader-only hard-delete behavior.

## Success Criteria

1. Home Job Workspace renders one row per file with action buttons in row columns.
2. Load, Remove, and Delete file actions still target the correct upload.
3. The UI no longer requires selecting a row before actions appear.
4. Focused Home and Docker tests pass.

## Outcome

- Replaced the selectable dataframe plus external action bar with a custom
  table-style layout.
- Each file row now shows metadata and its own action buttons in the same row.
- Verification:
  - `python3 -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py -q`
    passed with `13 passed`.
  - `docker compose run --rm marcedit-web python -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py tests/test_jobs_page.py tests/test_session_restore.py tests/test_jobs.py -q`
    passed with `64 passed`.

