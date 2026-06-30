# TASK-093 — Shared job access service and UI

**Status:** Completed
**Priority:** Tier 4 — Collaboration
**Parent:** TASK-086
**Depends on:** TASK-081, TASK-085
**Design ADR:** `docs/adr-collaboration-locking.md`

## Title

Let job owners share a job with editors/viewers and enforce `job_access` in
job listing/selection.

## Scope

- Add `jobs` helpers for granting, revoking, listing, and checking access.
- Make `jobs.list_jobs(user)` include jobs shared with the user, not only owned
  jobs.
- Add owner-only sharing controls to the Home job selector.
- Enforce roles: owner/editor/viewer.

## Success Criteria

1. Owners can grant/revoke editor/viewer access.
2. Shared jobs appear for invited users.
3. Viewers can select and inspect a shared job but cannot perform edit actions.
4. Focused tests and Docker suite pass before completion.

## Outcome

- Added job access helpers for grant, revoke, list, role lookup, and role
  enforcement.
- Updated job listing to include shared jobs with `access_role`.
- Added owner-only Home-page sharing controls for granting and revoking
  editor/viewer access.
- Final verification: `docker compose run --rm marcedit-web python -m pytest -q`
  passed with `856 passed, 5 skipped`.
