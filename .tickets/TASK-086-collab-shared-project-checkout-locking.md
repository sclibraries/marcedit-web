# TASK-086 — Collaboration epic: shared project + record check-out/locking

**Status:** Todo
**Priority:** Tier 4 — Collaboration (future-state epic; split during planning)
**Collaboration:** The shared-environment feature itself
**Source:** User decision 2026-06-17 — shared project + record check-out/locking
**Depends on:** TASK-073, TASK-081, TASK-082, TASK-083, TASK-085
**Design ADR:** `docs/adr-collaboration-locking.md`

## Title

Let two or more catalogers work a shared job concurrently via record/file
check-out, locking, presence, and an access list.

## Scope (epic — to be decomposed into sub-tickets during planning)

- Shared-project access control UI on top of TASK-081's schema (share/invite a
  job to another cataloger).
- Record-or-file check-out / locking on top of TASK-083's lock primitive: show
  who holds a lock; read-only view for non-holders; lock expiry / release.
- Presence indicators (who is currently in the job).
- Per-change attribution surfaced from TASK-082 provenance.
- Implement per `docs/adr-collaboration-locking.md`: hybrid checkout with
  record-level locks for ordinary editing, job-level locks for batch-wide
  mutations, and no real-time co-editing.

## Implementation Plan

Plan: `docs/superpowers/plans/2026-06-25-collaboration-checkout-locking.md`

Sub-tickets:

1. TASK-093 — Shared job access service and UI.
2. TASK-094 — Collaboration lock and version service.
3. TASK-095 — Record checkout and read-only edit UI.
4. TASK-096 — Job-level locks for batch-wide operations.
5. TASK-097 — Shared job presence indicators.
6. TASK-098 — Collaboration provenance display.

## Success Criteria

1. Two catalogers can open the same shared job; one checks out a record/file,
   the other sees it locked/read-only; on release the other can edit.
2. No lost updates under concurrent access (validated against TASK-083's
   guarantees).
3. Sharing respects the access list; provenance shows who changed what.
4. Behaviour matches the TASK-085 ADR; focused tests and the Docker test suite
   pass before completion.
