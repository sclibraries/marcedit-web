# TASK-122 — Home Job Workspace file actions

**Status:** Completed
**Priority:** Tier 2 — Shared cataloging usability
**Depends on:** TASK-119, TASK-120, TASK-121

## Title

Make files in Home Job Workspace actionable.

## Scope

- Add per-file actions to Home's **Files in this job** list.
- Support loading a selected durable upload into the active session.
- Support soft-removing a file from the selected job.
- Show hard-delete only to the original uploader.
- Preserve the existing Jobs page actions.

## Success Criteria

1. Home Job Workspace renders file actions next to attached MARC files.
2. `Load` opens the selected upload in View Records.
3. `Remove` soft-removes the upload and reruns the page.
4. `Delete file` is only available to the original uploader.
5. Focused Home, Jobs, and storage tests pass.

## Outcome

- Added Home Job Workspace action rows below **Files in this job**.
- `Load` calls `session.load_persisted_upload(...)` and opens View Records.
- `Remove` soft-removes the upload from the selected job.
- `Delete file` is shown only for files uploaded by the active user.
- Remove is only shown for owners/editors.
- Verification:
  - `python3 -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py -q`
    passed with `13 passed`.
  - `docker compose run --rm marcedit-web python -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py tests/test_jobs_page.py tests/test_session_restore.py tests/test_jobs.py -q`
    passed with `64 passed`.
