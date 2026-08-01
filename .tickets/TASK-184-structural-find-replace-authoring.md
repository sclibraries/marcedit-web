Title: Add structural and patterned Find and Replace authoring

Parent: TASK-174

Depends on: TASK-180

Scope:
- Extend TASK-180's deterministic Find and Replace engine and guided card with
  whole data-field replacement, field-tag changes, indicator changes, and
  validated tag ranges.
- Add structured pattern pieces for literal text, variable text, digits,
  character sets, anchors, and named captured values.
- Publish an explicit compatibility matrix for structural targets, match
  modes, and replacement actions.
- Reuse TASK-179's structured indicators-and-subfields controls for whole
  data-field replacement.
- Keep raw regex optional and keep all processing deterministic.

Success Criteria:
- Catalogers can author whole-field, retag, indicator, range, and structured
  pattern operations without writing Python.
- Every supported target/action combination is explicitly specified and
  covered by intent-focused tests; incompatible combinations fail loud.
- Named structured captures round-trip and preview without exposing generated
  regex as the source of truth.
- Preview and execution remain equivalent and non-mutating preview is proven.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: Completed

Review remediation: TASK-188

Plan: `docs/superpowers/plans/2026-08-01-task-184-structural-find-replace-authoring.md`

Design:
- `docs/superpowers/specs/2026-07-31-task-184-structural-find-replace-authoring-design.md`

Implementation checkpoint (2026-08-01):
- Added structural target/action matrix validation, whole-field replacement,
  retagging, indicators, tag ranges, named structured captures, deterministic
  modal preview, and compiler round-trip coverage.
- Verified the compatibility cells, preview non-mutation, and full Docker suite
  (`2042 passed, 5 skipped`).

TASK-188 review remediation (2026-08-01):
- Empty textual and structured matches fail before execution. Retag and
  indicator operations can target every selected field only through the
  explicit `all` match mode, and invalid raw-regex capture references fail
  during validation.
- Structural generated code uses recursive literal validation, retag source
  position is explicitly preserved, and the modal exposes both action and
  match controls for field-tag and indicator workflows.
