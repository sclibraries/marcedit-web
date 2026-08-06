Title: Add focused one-operation Quick field changes

Design: [Focused Quick field changes](../docs/superpowers/specs/2026-08-06-task-195-focused-quick-field-changes-design.md)

Scope:
- Expand Quick changes with cataloger-oriented one-time field operations:
  add field, delete field, add subfield, delete subfield, set indicators,
  copy field, move or retag field, swap two same-tag field occurrences, and
  remove exact duplicate fields.
- Keep Quick changes limited to one operation per Preview and Apply cycle.
- Add a shared filter-then-occurrence field selector with guided matching and
  an optional advanced regular-expression mode.
- Reuse the existing preview, stale-state, recoverable-version, snapshot,
  audit, and export boundaries without creating a saved task.

Success Criteria:
- Catalogers can identify a field by tag, optional indicators, optional
  subfield match, and first, last, numbered, or deliberately selected every
  matching occurrence.
- Missing requested occurrences skip only the affected record and are grouped
  by reason in Preview.
- Swap exchanges the source-order positions of two distinct same-tag fields
  while preserving each complete field's tag, indicators or control value,
  and ordered subfields.
- Add, delete, subfield, indicator, copy, move, and duplicate-removal behavior
  is explicit, validated, and described in plain language before Preview.
- Guided matching is the default; raw regular expressions are optional,
  validated, bounded, and never required for ordinary use.
- Preview and Apply use the same deterministic transformation and reject stale
  previews or changed source versions.
- Successful Apply produces the existing recoverable job-file version or
  Quick Load snapshot evidence; validation or write failure produces no
  partial application.
- Existing specialized Quick operations, Quick find/replace, saved tasks,
  imports, authorization, and AI behavior remain unchanged.
- Table-driven tests cover multiple same-tag fields, selector modes, missing
  occurrences, control/data restrictions, swap ordering, preview/apply
  equivalence, stale previews, and job/Quick Load persistence.

Status: Todo
