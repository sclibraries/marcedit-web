Title: Add explicit canonical MARC field reordering

Parent: TASK-174

Related: TASK-169

Scope:
- Add a quick action that reorders a selected MARC file into the application's
  documented canonical field order.
- Add the same deterministic operation as an optional task step, including a
  convenient final-step placement after other task operations.
- Preserve the relative order of repeated fields with the same tag unless a
  separately documented rule requires otherwise.
- Preview and summarize inversions and changes before writing output.
- Keep View faithful to source order and retain TASK-169's non-mutating warning;
  sorting occurs only through an explicit user action or saved task step.
- Define leader and control-field placement, numeric tag ordering, repeated-tag
  stability, malformed-tag handling, and output serialization behavior.

Success Criteria:
- A cataloger can run field reordering directly against a selected file without
  first creating a reusable task.
- A cataloger can add the identical operation to a task and place it last.
- Already ordered records are byte-equivalent apart from unavoidable,
  documented serializer behavior.
- Repeated fields retain their original relative order.
- Preview reports a bounded summary and does not mutate source or stored
  output.
- Malformed or unsupported tags fail loud or follow a documented deterministic
  policy; they are never silently dropped.
- Quick-action and task-step paths share one tested ordering implementation.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: Completed

Review remediation: TASK-188

Plan: `docs/superpowers/plans/2026-08-01-task-182-canonical-field-reordering.md`

Design:
- `docs/superpowers/specs/2026-07-31-task-182-canonical-field-reordering-design.md`

Implementation checkpoint (2026-08-01):
- Added one stable canonical numeric-tag transform for quick actions and task
  steps, inversion/representative before-after reporting, malformed-tag
  fail-closed handling, and stable duplicate ordering.
- Verified quick/task equivalence, preview non-mutation, and history paths in
  focused tests and the complete mounted-source Docker suite (`2042 passed,
  5 skipped`).

TASK-188 review remediation (2026-08-01):
- The shared inversion count is now O(n log n), quick preview uses that same
  implementation, and malformed-tag diagnostics retain record number zero.
- Structural retagging deliberately preserves source position; catalogers add
  this explicit operation when canonical order is required afterward.
