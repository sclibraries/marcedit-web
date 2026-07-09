# TASK-121 — Job upload UI actions

**Status:** Completed
**Priority:** Tier 2 — Shared cataloging usability
**Depends on:** TASK-120

## Title

Add load and remove actions for files attached to a job.

## Scope

- Let catalogers load a specific durable job upload into the active session.
- Let job editors/owners soft-remove an upload from the job file list.
- Let only the original uploader explicitly delete the underlying `.mrc` file.
- Keep viewer access read-only.

## Success Criteria

1. Loading a job upload restores that exact persisted file into session state.
2. The Jobs page renders per-file Load and Remove actions for editable job members.
3. Hard-delete action is only rendered for the original uploader.
4. Viewer role does not get mutation controls.
5. Focused page/session/job tests pass.

## Outcome

- Added `session.load_persisted_upload(upload_id)` to load a specific durable
  job upload into the active session.
- Added `jobs.get_upload_for_user(...)` for access-checked upload lookup.
- Added per-file Jobs page actions:
  - `Load` for job members;
  - `Remove` for editors/owners;
  - `Delete file` only for the original uploader.
- Kept the existing file table for scanning, with action rows below it.
- Verification:
  - `python3 -m pytest tests/test_upload_persistence.py tests/test_session_restore.py tests/test_jobs.py tests/test_job_schema.py tests/test_jobs_page.py -q`
    passed with `66 passed`.
  - `docker compose run --rm marcedit-web python -m pytest tests/test_upload_persistence.py tests/test_session_restore.py tests/test_jobs.py tests/test_job_schema.py tests/test_jobs_page.py -q`
    passed with `66 passed`.
  - `docker compose run --rm marcedit-web python -m pytest -q` passed with
    `929 passed, 5 skipped`.
