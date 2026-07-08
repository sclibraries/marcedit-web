# TASK-120 — Durable job upload storage

**Status:** Completed
**Priority:** Tier 2 — Shared cataloging data integrity
**Depends on:** TASK-118, TASK-119

## Title

Store each job upload as its own durable MARC file.

## Scope

- Stop overwriting signed-in uploads at one per-user `upload.mrc` path.
- Store each upload at a distinct path so every job file row points to the
  actual bytes uploaded for that row.
- Preserve the existing one active upload per user/session restore behavior.
- Add upload removal semantics that hide a file from normal job lists without
  deleting the actual `.mrc` by default.
- Allow hard deletion of an uploaded `.mrc` only when explicitly requested by
  the user who originally uploaded it.

## Success Criteria

1. Uploading two files to the same job produces two different persisted file
   paths.
2. Both files still exist after the second upload.
3. The active upload row still restores the current user session.
4. Normal job upload lists hide soft-removed files.
5. Hard deletion removes the file only when requested by the original uploader.
6. Focused storage and job tests pass.

## Outcome

- Added schema v10 upload removal metadata: `removed_at` and `removed_by`.
- Changed signed-in uploads to use unique durable per-upload directories under
  `data/uploads/<user>/jobs/<job-id>/<upload-id>/upload.mrc`.
- Kept one active upload per user for session restore, but clearing active
  state no longer deletes MARC bytes.
- Added `jobs.remove_upload(...)` for soft removal by job editors/owners and
  explicit hard deletion only by the original uploader.
- Updated deployment documentation for the new upload path layout.
- Verification:
  - `python3 -m pytest tests/test_upload_persistence.py tests/test_session_restore.py tests/test_jobs.py tests/test_job_schema.py tests/test_jobs_page.py -q`
    passed with `66 passed` after TASK-121 added upload actions.
  - `docker compose run --rm marcedit-web python -m pytest -q` passed with
    `929 passed, 5 skipped`.
