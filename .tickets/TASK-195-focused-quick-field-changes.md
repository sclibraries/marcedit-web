Title: Add focused one-operation Quick field changes

Design: [Focused Quick field changes](../docs/superpowers/specs/2026-08-06-task-195-focused-quick-field-changes-design.md)

Plan: [Focused Quick field changes implementation](../docs/superpowers/plans/2026-08-06-task-195-focused-quick-field-changes.md)

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
- Add a bounded, allowlisted structured-adapter envelope to the existing
  subprocess sandbox so Common field changes never interpolate request values
  into executable task source.

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
  validated, bounded, never executed in the Streamlit process, and never
  required for ordinary use.
- Preview and Apply use the same deterministic transformation and reject stale
  previews or changed source versions.
- Preview and Apply execute the fixed Common field changes adapter in the
  subprocess sandbox without invoking the task compiler or exposing a new
  saved-task or AI operation.
- Successful Apply produces the existing recoverable job-file version or
  Quick Load snapshot evidence; validation or write failure produces no
  partial application.
- Existing specialized Quick operations, Quick find/replace, saved tasks,
  imports, authorization, and AI behavior remain unchanged.
- Table-driven tests cover multiple same-tag fields, selector modes, missing
  occurrences, control/data restrictions, swap ordering, preview/apply
  equivalence, the operation/occurrence compatibility matrix, shared-helper
  equivalence, stale previews, and job/Quick Load persistence.
- The new controls live in a dedicated Quick field changes renderer;
  `render/tasks.py` only mounts it and supplies existing file/version context.

Status: In-Progress
