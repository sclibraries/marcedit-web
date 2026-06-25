# TASK-096 — Job-level locks for batch-wide operations

**Status:** Todo
**Priority:** Tier 4 — Collaboration
**Parent:** TASK-086
**Depends on:** TASK-094
**Design ADR:** `docs/adr-collaboration-locking.md`

## Title

Protect full-batch mutations with job-level locks.

## Scope

- Require job locks for full MARC editor save, task run snapshot/restore, upload
  replacement, and snapshot restore.
- Block record saves while a job lock is active.
- Release job locks on explicit completion/cancel and let expiry recover
  abandoned work.

## Success Criteria

1. Full-batch operations acquire a job lock or fail with a clear message.
2. Active record locks block job-level operations.
3. Active job locks block record-level saves.
4. Focused tests and Docker suite pass before completion.
