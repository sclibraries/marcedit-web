# TASK-192: Partner-pattern pymarc operations design

## Objective

Convert proven repeated external-task sequences into concise, editable native
operations that execute deterministically with pymarc. The importer must
represent cataloging intent rather than preserve redundant text-editing steps.

## Evidence boundary

TASK-191 pins 49 partner-library archives containing 1,239 instructions. The
current importer converts 693 occurrences and leaves 546 actionable blockers,
representing 166 unique unresolved source lines. Repetition prioritizes an
instruction for investigation but does not prove its semantics. A new adapter
requires documented behavior or representative MARC before/after evidence.

## Native operations

### Build fields for each matching source field

The operation selects source fields through existing structured predicates and
creates one or more destination fields for every match. Templates reference
the selected field's indicators and subfields plus explicitly permitted record
values. It defines occurrence selection, missing-source behavior, destination
collision behavior, and a maximum number of destination fields per record.

### Institution mapping profile

A structured row contains institution name, destination tag, location, link
label, identifier suffix, and fixed subfields. Applying a profile to each
selected 856 replaces the repeated 945-949 build, copy, edit, and retag chain.
Rows remain editable in the form authoring UI and are never stored as Python.

### Copy fields

Copy selects source fields, clones them through pymarc, assigns the destination
tag, and applies an explicit existing-target policy. Optional structured
predicates replace unproven external filter flags. The operation never mutates
the source unless a separate removal action is present.

### Conditional and subfield actions

Existing field predicates expand to reviewed Leader, control-field, indicator,
and subfield conditions. Subfield changes use named actions: add, set, replace
matched text, replace whole value, prepend, append, or remove. External numeric
option codes are provenance only and never enter the native definition.

## Pattern migration

The external importer parses the complete ordered task before adapting it. A
pattern registry may consume a reviewed contiguous source range and emit one
native operation with provenance for every consumed line. Overlapping matches
fail closed. If any required line, column, flag, or condition differs, the
sequence remains unconverted and receives a cataloger-facing recommendation.

The importer presents the consolidated operation first. Raw source ranges,
fingerprints, and adapter evidence remain collapsed under Technical details.
Preview and save/reopen must preserve the native operation losslessly.

## TASK_LIST dependencies

TASK_LIST is composition, not inherently iteration. A reference converts only
when its target is available and has a verified identity. Missing references,
including the absent partner 945 looping task, remain blocking cards that ask
the cataloger to import or select the dependency. The importer never infers a
referenced task solely from its display name. TASK-192 does not add nested-task
execution: implementing composition and cycle detection requires a separate
ticket after available dependencies establish the required identity model.

## Preview and execution safety

Preview and execution call the same pure transformation engine. Results report
records inspected, source fields matched, destination fields created, existing
fields replaced, and records skipped. Expansion is bounded per record and for
the complete batch. Invalid templates, missing mappings, collisions without a
policy, and exceeded bounds fail before committing output. Field ordering is
preserved unless the task contains the explicit canonical-order operation.

## Testing

- Characterize every accepted source signature before adding its adapter.
- Use MARC golden records for the repeated 856 and 945-949 workflows.
- Compare consolidated output to the documented expected record, not to opaque
  generated source text.
- Cover zero, one, and multiple source fields; duplicates; missing subfields;
  collision policies; ordering; and expansion limits.
- Regenerate the partner-corpus converted/blocker report and require zero
  unclassified items and zero blockers without a next action.
- Run focused, full source-mounted, and Python 3.9 Docker suites and report all
  skips.

## Non-goals

- Arbitrary cataloger-authored Python.
- Automatic support for undocumented external option numbers.
- Byte-for-byte emulation of an external application's internal engine.
- Guessing the content of absent TASK_LIST dependencies.
