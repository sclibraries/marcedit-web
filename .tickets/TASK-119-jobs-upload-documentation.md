# TASK-119 — Clarify job file attachment workflow

**Status:** Completed
**Priority:** Tier 4 — Cataloger workflow clarity
**Depends on:** TASK-118

## Title

Clarify how catalogers get back to Job Workspace and see which MARC files are
attached to the selected job.

## Scope

- Add documentation explaining Quick Load versus Job Workspace.
- Make the Job Workspace path clearly support uploading a `.mrc` file into the
  selected job.
- Keep the selected start path reflected in the URL so catalogers can return to
  the Job Workspace path.
- Show the files attached to the selected job on Home.
- Preserve Quick Load behavior: one-off uploads attach to `Personal uploads`.

## Success Criteria

1. Catalogers can upload a file directly into the selected job from Home.
2. Quick Load still attaches uploads to the default `Personal uploads` job.
3. Home shows the MARC files already attached to the selected job.
4. Changing the Home start path updates a URL query parameter.
5. Documentation explains how jobs, files, sharing, review notes, and archive
   status work.
6. Focused tests pass.

## Outcome

- Added a Job Workspace upload control so a selected job can receive a `.mrc`
  file directly from Home.
- Replaced Home tabs with a URL-backed start path selector using `?start=quick`
  and `?start=jobs`.
- Added a visible **Files in this job** list to Home for the selected job.
- Added `docs/jobs.md` explaining Quick Load, Job Workspace, adding files,
  sharing, review notes, activity, and archive/restore.
- Linked the Jobs guide from `README.md`.
- Verification: `python3 -m pytest tests/test_home_page_jobs.py tests/test_app_pages.py -q`
  passed with `10 passed`.
