# TASK-118 — Jobs management UI

**Status:** Completed
**Priority:** Tier 4 — Cataloger workflow clarity
**Depends on:** TASK-081, TASK-093
**Design:** `docs/superpowers/specs/2026-07-07-jobs-workspace-ui-design.md`
**Plan:** `docs/superpowers/plans/2026-07-08-jobs-workspace-ui.md`

## Title

Add a clear Jobs UI for reviewing jobs, attached MARC uploads, sharing, and
archive/delete actions.

## Scope

- Add a user-facing jobs view that lists jobs available to the current user by
  name, owner, role, created date, and status.
- Show the `.mrc` uploads attached to each job, including filename, record
  count, size, upload time, and active flag.
- Provide an owner-only job archive/delete action using the existing
  `jobs.active` flag rather than hard-deleting rows.
- Keep the existing Home-page upload selector working, but reduce confusion by
  making job membership and attached files inspectable outside the selector.
- Decide whether this lives as a new Jobs page or as a Home/Admin subsection
  before implementation.

## Success Criteria

1. Catalogers can see every active job they own or can access.
2. Catalogers can see which uploaded `.mrc` files are associated with each job.
3. Owners can archive/delete non-default jobs without losing upload history.
4. Archived jobs disappear from normal selection but remain queryable for
   history/audit.
5. Focused UI/helper tests pass, and the relevant broader test slice passes
   before completion.

## Outcome

- Added schema/helper support for advisory job status, review notes, activity,
  archive/restore, and job summaries.
- Added a private Jobs page with list/detail views, attached upload visibility,
  sharing, review notes, status controls, activity, and archive/restore.
- Cleaned Home into Quick Load and Job Workspace paths.
- Verification:
  - `python3 -m pytest tests/test_job_schema.py tests/test_jobs.py tests/test_jobs_page.py tests/test_home_page_jobs.py tests/test_app_pages.py -q`
    passed with `43 passed`.
  - `docker compose run --rm marcedit-web python -m pytest -q` passed with
    `920 passed, 5 skipped`.
