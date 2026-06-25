# TASK-085 — Collaboration design spike / ADR

**Status:** Todo
**Priority:** Tier 4 — Collaboration (future-state, design only)
**Collaboration:** Locks the model before any collaboration code is written
**Source:** User decision 2026-06-17 — shared project + record check-out/locking
**Depends on:** TASK-081, TASK-082, TASK-083

## Title

Decide and document the shared-project + record check-out/locking model before
building it, including the concurrency-scale ceiling of the current substrate.

## Scope

- Author an ADR in `docs/` covering:
  - Lock granularity (file vs record) and why.
  - Lock acquisition / expiry / steal policy; what happens when a lock lapses
    mid-edit.
  - Conflict handling and lost-update prevention.
  - Presence / lock-holder UX.
  - How locking maps onto Streamlit's rerun model and the SQLite substrate
    (building on TASK-083's lock primitive).
  - Deployment-scale limit: how many concurrent catalogers the single-process
    Streamlit + SQLite-WAL substrate supports, and the concrete trigger that
    would force a re-architecture (e.g. Postgres / multi-process).
- Confirm the chosen model against the job/provenance/concurrency foundations.

## Success Criteria

1. An ADR records the locking model, conflict policy, presence UX, and the
   concurrency-scale ceiling with its re-architecture trigger.
2. The ADR is referenced by TASK-086's scope.
3. Design only — no code changes.
