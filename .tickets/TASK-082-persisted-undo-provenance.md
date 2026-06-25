# TASK-082 — Persisted undo + user-attributed provenance

**Status:** Todo
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
