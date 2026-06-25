# TASK-094 — Collaboration lock and version service

**Status:** Todo
**Priority:** Tier 4 — Collaboration
**Parent:** TASK-086
**Depends on:** TASK-083, TASK-085, TASK-093
**Design ADR:** `docs/adr-collaboration-locking.md`

## Title

Build a job/record checkout service on top of advisory locks with version-token
lost-update protection.

## Scope

- Add a focused collaboration service module that wraps `locks`.
- Implement record lock acquire/renew/release with job-lock conflict checks.
- Implement job lock acquire/renew/release with record-lock conflict checks.
- Add a job version token suitable for save-time lost-update checks.

## Success Criteria

1. Record lock acquisition fails while a job lock is active.
2. Job lock acquisition fails while any record lock for the job is active.
3. Expired locks can be reacquired; non-holders cannot release active locks.
4. Save-time version checks block stale edits.
5. Concurrent tests and Docker suite pass before completion.
