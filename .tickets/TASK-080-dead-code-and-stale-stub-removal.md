# TASK-080 — Remove dead code and the stale Workspace diff stub

**Status:** Todo
**Priority:** Tier 2 — Quality (clarity)
**Source:** Deep code audit 2026-06-17 — quality findings (dead code / naming)

## Title

Delete confirmed-unused functions and parameters and refresh the stale
"coming soon" diff stub.

## Scope

- Remove (after confirming no production callers via grep):
  `tooltips.variable_field_subfield_codes`, `search._unquote`, the dead
  `source_bytes` parameter on `_offer_download_binary`, and
  `editor.save_user_task` / `delete_user_task` if superseded by `task_db`.
  Decide explicitly on `viewer.parse_indices` (tests-only): remove or document.
- Replace `render/diff.py`'s stale stub that references already-shipped
  milestones as "coming soon".
- Rename the misleading one-liners `leader_type` / `leader_biblevel`, and
  disambiguate the two unrelated `fingerprint_record` functions (or fold into
  TASK-078).

## Success Criteria

1. Each removal is justified by grep output showing no production callers
   (recorded in the ticket / PR).
2. The app plus focused tests and the Docker test suite pass after removal.
3. `render/diff.py` reflects the actual current feature state.
