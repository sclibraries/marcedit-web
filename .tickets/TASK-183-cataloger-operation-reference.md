Title: Add a cataloger-facing task operation reference

Parent: TASK-174

Scope:
- Document every deterministic operation available in the Tasks form.
- Explain in cataloger language what each operation matches, what it changes,
  when it skips, and how it handles missing or invalid data.
- Include transparent MARC syntax, representative before/after examples, and
  guidance about when each operation is appropriate.
- Document matching mode, occurrence count, replacement scope, preservation
  of surrounding data, record conditions, and existing-field behavior wherever
  those concepts apply.
- Link the checked-in reference from contextual help in the Tasks form without
  hiding the underlying technical representation.
- Keep documentation synchronized with the executable operation palette and
  deterministic behavior; do not add AI-generated guidance.

Success Criteria:
- Every operation in the supported Tasks palette has a cataloger-facing entry.
- Each entry states its inputs, scope, effect, skip/error behavior, and at least
  one MARC before/after example.
- Find/Replace documentation distinguishes matched-text replacement from whole
  subfield or whole-field replacement and explains preservation on both sides.
- A freshness test fails when a supported operation lacks documentation.
- The Tasks form links to the reference and provides concise contextual help.
- Cataloger review reports no ambiguous or unexplained operation behavior.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: Todo

Design:
- `docs/superpowers/specs/2026-07-31-task-183-cataloger-operation-reference-design.md`
