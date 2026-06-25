# TASK-098 — Collaboration provenance display

**Status:** Todo
**Priority:** Tier 4 — Collaboration
**Parent:** TASK-086
**Depends on:** TASK-082, TASK-093
**Design ADR:** `docs/adr-collaboration-locking.md`

## Title

Surface job snapshots as collaborative "who changed what" history.

## Scope

- Add a job history/provenance panel available to shared-job users.
- Show user, timestamp, kind, label, record index/source when present, and
  before/after downloads.
- Restrict restore actions to owner/editor roles.
- Keep the existing rollback behavior from TASK-082.

## Success Criteria

1. Shared-job users can inspect provenance for the selected job.
2. Owner/editor users can restore snapshots; viewers cannot.
3. Provenance clearly identifies who changed what and when.
4. Focused tests and Docker suite pass before completion.
