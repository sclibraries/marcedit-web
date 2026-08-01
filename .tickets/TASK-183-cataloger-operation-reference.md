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

Status: Completed

Review remediation: TASK-188

Plan: `docs/superpowers/plans/2026-08-01-task-183-cataloger-operation-reference.md`

Design:
- `docs/superpowers/specs/2026-07-31-task-183-cataloger-operation-reference-design.md`

Implementation checkpoint (2026-08-01):
- Added a registry-backed in-app reference and generated Markdown guide with
  explicit inputs, preservation/skip/error behavior, and sanitized MARC
  before/after examples for every palette operation.
- Added freshness, search, and rendering tests; the complete mounted-source
  Docker suite passes (`2042 passed, 5 skipped`).

TASK-188 review remediation (2026-08-01):
- RDA carrier, relator preservation, 264 publication indicator, and explicit
  008-position behavior are reflected in the registry and regenerated guide.
- A runtime image that intentionally omits the generated repository guide now
  reports one loud freshness-test skip; the mounted-source check remains
  authoritative and passing.
