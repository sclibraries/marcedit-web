# TASK-078c — Consolidate identical/duplicated helpers (mechanical, no behavior change)

**Status:** Completed — implemented, reviewed (clean), merged to local main
**Worktree:** `.claude/worktrees/task-078c-mechanical` (branch `worktree-task-078c-mechanical`)
**Parent:** TASK-078 (DRY consolidation) — sub-ticket 3 of 4

## Resolution (2026-06-18)

Three consolidations, 4 commits (0bdeb22, 2f63159, 2b9a810, a19609e), reviewed
clean (Ready to merge: Yes; 0 Critical/Important). Full Docker suite 753 passed.

**Accepted micro-change (review Minor #1):** in `views/6_Diff.py`, the `adds`
and `deletes` download names now call `session.stamped_filename(...)`
independently, so their timestamp suffixes could differ by 1s if the wall clock
crosses a second boundary between the two calls (previously they shared one
stamp). Cosmetic only — two separate downloads, no code compares them — so
accepted rather than re-introducing an inline stamp at that one site.
**Priority:** Tier 2 — Quality (clarity; zero behavior change)
**Source:** Deep code audit 2026-06-17; scoped via brainstorm 2026-06-18

## Scope (three clean wins; session-key constants deferred to TASK-078c-keys)

1. `_is_control_tag` — byte-identical in `rules_validate.py` and `mrk_parser.py`
   → move to `transforms.py` as public `is_control_tag(tag)`; both import it.
2. `_record_issue` — byte-identical in `rules_validate.py` and `preflight.py`
   → move to `errors.py` as public `make_record_issue(...)` (errors.py owns
   `Issue` and is a leaf module); both import it.
3. `_stamped_filename` — 9 divergent inline copies → one primitive in
   `session.py`: `stamped_filename(base: str, suffix: str = ".mrc") -> str`
   returning `f"{base}_{stamp}{suffix}"`. Each caller computes its `base`;
   produced filenames preserved exactly.

## Non-Goals

- Session-state key constants (`view_index`, `issues_cache`) — deferred to
  TASK-078c-keys (8+ files of literal→constant churn, marginal value).

## Success Criteria

1. Each listed duplicate has exactly one definition; all call sites updated.
2. Existing `rules_validate`, `preflight`, `mrk_parser` tests stay green
   (proves the identical moves changed nothing); `stamped_filename` has a
   focused shape test.
3. Focused tests and the Docker test suite pass before completion.
