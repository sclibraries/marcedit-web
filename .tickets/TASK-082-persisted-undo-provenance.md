# TASK-082 — Persisted undo + user-attributed provenance

**Status:** In-Progress
**Priority:** Tier 3 — Service foundation
**Collaboration:** Per-change attribution is the collaboration audit foundation
**Source:** Deep code audit 2026-06-17 — horizon (undo/rollback + provenance)
**Depends on:** TASK-073 (identity), TASK-081 (job model)

## Title

Persist run/edit history with before/after snapshots and per-change user
attribution, enabling one-click rollback and a queryable "who changed what".

## Scope

- Replace the in-memory last-5 `run_history` (lost on tab close) with persisted
  per-job snapshots under `data/` (before/after `.mrc` references + the existing
  `RunSummary`).
- Attribute every run/edit to a `user_id` (depends on TASK-073 for trustworthy
  identity).
- Add a "restore previous version" action.

## Success Criteria

1. A batch run can be rolled back to its pre-run state in one action, surviving
   restart / tab close.
2. History persists across sessions and records who ran/edited what, and when.
3. Snapshot storage respects job ownership and caps.
4. Focused tests and the Docker test suite pass before completion.

## Implementation Plan

Ticket link: `.tickets/TASK-082-persisted-undo-provenance.md`

1. Persistence foundation:
   - Add schema v7 `job_snapshots` with job/user/kind/label, before/after file
     paths, summary JSON, and timestamp.
   - Add `marcedit_web.lib.provenance` helpers to create/list snapshots,
     restore pre-change bytes, and prune old snapshots per job.
   - Commit.
2. Mutation integration:
   - Record snapshots around Tasks batch runs and MarcEditor/full-record saves.
   - Add restore action where history is rendered.
   - Commit.
3. Final verification:
   - Docker suite, docs, and ticket completion.

## Progress

- 2026-06-25: Added schema v7 `job_snapshots` persistence and provenance
  helpers for create/list/restore/prune.
- 2026-06-25: Verified foundation with
  `python3 -m pytest tests/test_provenance.py tests/test_db.py tests/test_job_schema.py tests/test_jobs.py -q`,
  `python3 -m compileall -q marcedit_web/lib/provenance.py marcedit_web/lib/db.py`,
  and `git diff --check`.
- 2026-06-25: Added job snapshot recording for task runs and full MARC
  editor saves, plus a Tasks-page job snapshot restore/download view.
- 2026-06-25: Verified integration with
  `python3 -m pytest tests/test_session.py tests/test_snapshot_actions.py tests/test_provenance.py -q`,
  `python3 -m compileall -q marcedit_web/lib/session.py marcedit_web/lib/snapshot_actions.py marcedit_web/render/tasks.py marcedit_web/render/edit.py`,
  `git diff --check`,
  `docker compose run --rm marcedit-web python -m pytest tests/test_session.py tests/test_snapshot_actions.py tests/test_provenance.py -q`,
  and Docker imports for `marcedit_web.render.tasks` and
  `marcedit_web.render.edit`.
