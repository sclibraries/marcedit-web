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

Status: Todo
