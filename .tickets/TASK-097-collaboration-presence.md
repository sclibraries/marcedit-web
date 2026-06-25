# TASK-097 — Shared job presence indicators

**Status:** Todo
**Priority:** Tier 4 — Collaboration
**Parent:** TASK-086
**Depends on:** TASK-093
**Design ADR:** `docs/adr-collaboration-locking.md`

## Title

Show lightweight shared-job presence based on recent activity.

## Scope

- Add a presence heartbeat table/helper for job viewers.
- Update presence on normal Streamlit reruns for signed-in users with selected
  jobs.
- Show active users and lock holders in the job UI.
- Prune stale presence rows.

## Success Criteria

1. Recent job viewers appear in the shared job UI.
2. Stale presence expires automatically.
3. Presence is advisory only; `job_access` and locks remain authorization.
4. Focused tests and Docker suite pass before completion.
