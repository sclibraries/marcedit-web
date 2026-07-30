Title: Add structured deterministic Find and Replace task authoring

Parent: TASK-174

Scope:
- Extend the existing Tasks form with one guided Find and Replace operation
  after completed TASK-179 establishes the shared authoring patterns.
- Cover one control-field value, one subfield code, or all subfield values in
  one tag.
- Cover contains, starts-with, ends-with, whole-value, and optional raw-regex
  matching; matched-text, whole-selected-value, prepend, and append behavior;
  first/all occurrences; and case handling.
- Block empty-find SUBFIELD_EDIT imports and submission of existing generated
  empty-find operations because Python empty-string replacement silently
  inserts text between every character.
- Preserve existing saved operation semantics and defer external conversion,
  structural field/tag/indicator changes, tag ranges, and structured patterns
  to TASK-184 and TASK-185.
- Keep the work deterministic and reviewable; do not add AI task generation.

Success Criteria:
- Catalogers can express the Smith 035 TFeba replacement through labeled
  controls and preview the identifier-preserving result before execution.
- Replacement scope and preservation behavior are explicit and covered by
  intent-focused tests.
- Advanced raw regex remains available, round-trips exactly, and requires a
  current successful sandbox preview.
- Save/reopen is lossless and existing saved operation kinds retain their
  established behavior.
- Quick Find/Replace and AI drafting behavior remain unchanged, verified by
  characterization tests.
- Empty-find imports and already-saved generated empty-find form operations
  fail loud instead of executing.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: Todo

Design:
- `docs/superpowers/specs/2026-07-30-task-180-structured-find-replace-authoring-design.md`
