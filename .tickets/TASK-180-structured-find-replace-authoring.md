Title: Add structured deterministic Find and Replace task authoring

Parent: TASK-174

Scope:
- Extend the existing Tasks form with structured Find and Replace operations
  after TASK-179 establishes the shared authoring patterns.
- Cover field, subfield, indicator, regular-expression, prefix, suffix, and
  preserve-before/preserve-after behavior without requiring catalogers to
  write generated Python.
- Translate only externally imported signatures whose semantics are known
  exactly and keep ambiguous flags blocking and visible.
- Keep the work deterministic and reviewable; do not add AI task generation.

Success Criteria:
- Catalogers can express the Smith CORE replacement and subfield-edit examples
  through labeled controls and preview the result before execution.
- Replacement scope and preservation behavior are explicit and covered by
  intent-focused tests.
- Save/reopen and exact supported-import round trips are lossless.
- Unsupported or ambiguous external instructions fail loud.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: Todo
