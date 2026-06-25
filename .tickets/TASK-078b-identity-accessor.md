# TASK-078b — Single cached identity accessor

**Status:** Completed — implemented, reviewed (clean), merged to local main
**Worktree:** `.claude/worktrees/task-078b-identity` (branch `worktree-task-078b-identity`)
**Resolution (2026-06-18):** 2 commits (b36e9a0, 34208f1). 15 render/views inline reads + handle_upload now route through `session.current_user_id()` (cached). init/restore/`_current_user_for_enforcement` stay inline by design. Reviewed clean (Ready: Yes); Docker 757 passed.
**Parent:** TASK-078 (DRY consolidation) — sub-ticket 2 of 4
**Priority:** Tier 2 — Quality (finishes TASK-073's deferred single-point-identity goal)

## Scope

- Add `session.current_user_id() -> str` returning `st.session_state.get("user")
  or ANONYMOUS` — the cached identity captured once at `init()` via
  `current_user()` (OAuth + attestation-gated post-TASK-073).
- Replace the ~15 inline `st.session_state.get("user", "anonymous") or
  "anonymous"` reads (and the sidebar `.get("user", "anonymous")` variants)
  across render/ and views/ with `session.current_user_id()`.

## Decision

**Cached read, not re-evaluate** (user-flagged fork, resolved 2026-06-18). The
accessor returns the cached `session_state["user"]`, not a fresh
`current_user()` call, to preserve exact behavior and avoid re-running
OAuth/header logic per call.

## Non-Goals

- Do not change `current_user()` or the attestation gate (TASK-073, done).
- Sidebar render decisions and audit-event wiring stay as-is structurally.

## Success Criteria

1. One accessor; all inline `session_state["user"]` reads route through it.
2. No behavior change; focused test for the accessor; existing suites green.
3. Focused tests and the Docker test suite pass before completion.
