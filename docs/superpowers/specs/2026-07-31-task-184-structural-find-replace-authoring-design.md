# TASK-184 Structural Find and Replace Authoring Design

**Ticket:** [TASK-184](../../../.tickets/TASK-184-structural-find-replace-authoring.md)

**Depends on:** TASK-180

**Status:** Approved

## Purpose

TASK-180 provides safe value-level Find and Replace. TASK-184 extends the same
guided operation to structural MARC changes without requiring catalogers to
write Python or regular expressions.

## Goals

- Keep one progressive **Guided find and replace** operation.
- Add whole data-field, tag, indicator, and tag-range targets.
- Add structured patterns and named captures whose stored intent is not regex.
- Keep preview and execution on one deterministic engine.
- Publish and test every supported target/action combination.

## Non-Goals

- Importing external task syntax; TASK-185 owns adapters.
- Replacing the existing simple Move field or Set indicators operations.
- Treating generated regex as canonical storage.
- Adding AI drafting or natural-language execution.

## Cataloger Workflow

The first control asks **What do you want to change?** and offers:

- control-field value;
- one subfield;
- all subfields in one tag;
- complete data field;
- field tag;
- indicators; or
- fields in a tag range.

Only compatible matching and replacement controls appear. Simple
unconditional retagging and indicator changes remain available through the
existing focused operations; the guided operation is for conditional or
patterned changes.

Setup remains beside Preview in TASK-186's Workspace.

## Structured Pattern Model

Patterns are ordered pieces:

- literal text;
- any text;
- one or more digits;
- one or more characters from an explicit allowed set;
- start of value; and
- end of value.

Variable pieces may have a unique cataloger-supplied capture name. Replacement
values are ordered literal pieces and references to those named captures.
Names use a conservative identifier grammar, cannot repeat, and cannot be
referenced before definition.

The engine may compile pieces to a regular expression internally. Generated
regex is visible only under Technical details. Structured pieces and named
references remain canonical storage and round-trip exactly.

## Tag Ranges

Ranges store inclusive `start_tag` and `end_tag` values. Both are exactly
three numeric characters and the start cannot exceed the end.

Control fields `001` through `009` and data fields `010` through `999` are
separate target classes. A range cannot cross that boundary. Leader is never
part of a range. Indicator, subfield, or complete-data-field actions cannot be
applied to control fields.

## Compatibility Rules

The design requires a checked-in compatibility matrix. At minimum:

- value targets support the TASK-180 match and replacement actions;
- complete data fields support structured matching plus complete structured
  field replacement;
- field-tag targets support exact tag or validated data-field range selection
  and replacement with one valid destination tag;
- indicator targets support exact/blank/any indicator conditions and setting
  either indicator while leaving the other unchanged;
- range selection restricts which fields are visited but never changes
  occurrence or replacement semantics; and
- incompatible target, match, action, or field-class combinations fail
  validation before preview or compilation.

The plan must spell out the full matrix as table-driven test data rather than
leaving cells to implementation judgment.

## Engine and Storage

TASK-180's normalized request grows only versioned structural fields. One pure
engine accepts a record and normalized request and returns a structured change
summary. Compiler output calls that same engine through the existing
`transforms` exposure. Preview deep-copies records before calling it.

Existing TASK-180 definitions remain valid and retain their meaning. Unknown
future target, piece, or action values remain visible and blocking; opening an
editor never coerces them to defaults.

## Preview

Preview shows the first bounded changed records, before/after MARC, matched
field/value counts, discarded-value counts, skipped records, and validation or
runtime errors. Preview currency remains bound to request, store identity, and
store revision.

## Failure Handling

- Empty or invalid pattern pieces block save and preview.
- Invalid tag ranges and field-class crossings block save and preview.
- Missing capture references block save and preview.
- A record-specific malformed field produces a reported deterministic failure;
  the source record and store remain unchanged.
- No partial task output is adopted after a failed operation.

## Testing

Table-driven tests cover every matrix cell and every structured piece. Tests
prove structured round-trip, capture substitution, range boundaries, control
versus data-field rejection, repeated-field stability, non-mutating preview,
preview/execution equivalence, save/reopen, and existing TASK-180 behavior.

The native compiler contract is regenerated only if the intentional compiler
output changes and is verified against every golden definition. Focused and
complete mounted-source Docker suites report every skip. Independent review
must find no unresolved Critical or Important issue.

## Rollout

This is application and task-definition work only. It changes no production
path, service, proxy, worker topology, authentication, or ITS-managed unit.
