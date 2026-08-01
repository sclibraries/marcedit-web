Title: Persist unresolved task-import diagnostics after Streamlit reruns

Parent: TASK-174

Scope:
- Preserve the result of a MarcEdit text or archive import across the
  immediate Streamlit rerun so catalogers can read it.
- For rejected imports, keep the fail-closed explanation and every bounded
  unresolved source instruction visible long enough to review and recreate.
- Distinguish successful imports, partially rejected archive entries, quota
  failures, unresolved instructions, and unexpected exceptions without
  silently converting one outcome into another.
- Clear stale import results when a new import attempt begins or the task
  editor lifecycle is reset.
- Do not expand MarcEdit instruction compatibility; TASK-181, TASK-184, and
  TASK-185 own new deterministic conversions.

Success Criteria:
- The warning beginning “Not imported: this task contains unresolved external
  instructions” remains visible after the import-triggered rerun.
- The bounded unresolved-instruction list and omitted-count caption remain
  visible with the warning.
- Successful text and archive imports retain their existing behavior and show
  a durable success result.
- A later import attempt replaces the previous result rather than combining
  unrelated diagnostics.
- Focused tests reproduce the disappearing-message behavior before the fix
  and verify text, archive, success, rejection, and lifecycle-reset outcomes.
- Complete Docker verification reports every skip, and independent review has
  no unresolved Critical or Important findings.

Status: Completed

Review remediation: TASK-188

Design:
- `docs/superpowers/specs/2026-07-31-task-187-persistent-import-diagnostics-design.md`

Plan:
- `docs/superpowers/plans/2026-08-01-task-187-persistent-import-diagnostics.md`

Implementation checkpoint (2026-08-01):
- Import results are normalized and persisted across reruns, with bounded
  unresolved lines, migration fingerprints/choices, archive entry isolation,
  quota and exception categories, lifecycle clearing, and immediate Dismiss.
- Focused workspace tests and the complete mounted-source Docker suite pass
  (`2042 passed, 5 skipped`).

Historical remediation review (superseded 2026-08-01):
- Before implementation, the review identified malformed session payloads,
  warning-copy persistence, dismissal rerun behavior, and missing outcome
  coverage as blockers. The implementation checkpoint above records their
  resolution; checkpoint commit `c1dab43` preserves the completed work.
- TASK-188 reopened this ticket only to remove contradictory historical text
  and rerun final verification after the broader review fixes.

TASK-188 verification (2026-08-01):
- The contradictory pre-implementation blocker paragraph is now explicitly
  historical. Dismissal clears the durable result and reruns immediately, as
  verified in the existing focused tests.
