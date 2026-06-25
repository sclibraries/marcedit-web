# TASK-078c-keys — Session-state key constants

**Status:** Todo (deferred from TASK-078c)
**Parent:** TASK-078 (DRY consolidation)
**Priority:** Tier 2 — Quality (low value, high churn — do opportunistically)

## Scope

Collapse the scattered `"view_index"` and `"issues_cache"` session-state string
literals (8+ render/view modules) into named constants in `session.py`, imported
at each use site. Typo-safety + single source of truth.

## Why deferred

Pure literal→constant churn across many files for marginal benefit, and the
highest regression surface of the 078c batch. Split out so the three clean
helper consolidations (TASK-078c) ship without that noise.

## Success Criteria

1. `"view_index"` / `"issues_cache"` referenced via the session constants
   everywhere (no remaining bare literals outside session.py).
2. No behavior change; existing tests pass.
