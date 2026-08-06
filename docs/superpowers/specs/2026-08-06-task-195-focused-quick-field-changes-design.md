# TASK-195 Focused Quick Field Changes — Design

**Ticket:** [TASK-195](../../../.tickets/TASK-195-focused-quick-field-changes.md)

## Purpose

Quick changes are for a common edit that a cataloger needs once against the
currently loaded file. They should not require naming, saving, organizing, or
later deleting a task. This program expands the existing preview-first Quick
batch workflow with a focused set of generic MARC field operations while
preserving a clear boundary: one Quick operation per Preview and Apply cycle;
multi-step, reusable, templated, or institution-specific work remains a saved
task.

The existing specialized Quick operations and Quick find/replace remain
available and unchanged.

## Cataloger Workflow

Quick changes presents a **Common field changes** group whose operations are
alphabetized by cataloger-facing label:

- Add field
- Add subfield
- Copy field
- Delete field
- Delete subfield
- Move or retag field
- Remove exact duplicate fields
- Set indicators
- Swap field occurrences

The cataloger chooses exactly one operation, completes guided controls, reads
a plain-language summary, previews the loaded batch, and applies only from a
current successful preview. Nothing is added to the task library.

The summary names both the selection and the change. For example:

> In each record, find 070 fields. Swap the first matching 070 with the second
> matching 070. Records without two matching fields will be skipped.

## Shared Field Selector

All operations that act on existing fields use the same deterministic
filter-then-occurrence selector. A selector contains:

- an exact three-character MARC tag;
- indicator 1 and indicator 2 filters for data fields, each expressed as
  **Any**, **MARC blank**, or one exact character;
- an optional subfield code and value filter;
- a guided value mode: **Exact**, **Contains**, **Starts with**, or **Ends
  with**;
- a case-sensitive/case-insensitive choice; and
- an occurrence chosen after filtering: **First**, **Last**, **Every matching
  field**, or a one-based numbered occurrence.

Every matching field is offered only when the chosen operation has defined
multi-field semantics. Swap requires two selectors for the same tag; each
selector must resolve to one distinct field. A numbered occurrence is bounded
to 1–999. Match text and raw expressions use the existing bounded request-size
contract rather than accepting unbounded session or URL state.

Control fields reject indicator and subfield filters. Leader `000` is not a
field selector target; existing Leader Quick controls remain authoritative.
The selector is a pure library component with no Streamlit, database, session,
or file dependency, so validation, preview, and application use identical
selection semantics.

### Advanced Regular Expressions

Guided matching is the default. A collapsed **Advanced: regular expression**
choice changes only the optional subfield-value matcher to raw regex. It is
never required for ordinary selection.

Raw regex requests reuse the existing bounded canonical-request and sandbox
validation contract. They must not compile or execute in the Streamlit
process. Syntax errors, validation timeouts, cancellations, oversized
requests, and sandbox failures block Preview with bounded cataloger-facing
errors. Apply additionally requires a current successful preview of the exact
canonical request and source revision.

## Operation Semantics

### Add field

Add either a control field value or a data field with explicit indicators and
repeatable subfield rows. The record scope is one of:

- every record;
- only when the tag is absent; or
- only when an identical complete field is absent.

An identical data field has the same tag, indicators, ordered subfield codes,
and ordered subfield values. An identical control field has the same tag and
value. A request contains at most 100 added subfield rows.

### Delete field

Remove the fields resolved by the selector. First, last, numbered, and every
matching field are supported. No tag range or wildcard is inferred from an
exact tag; the existing specialized 9xx cleanup remains separate.

### Add subfield

Append or prepend one explicit code/value pair to each selected data field.
The cataloger chooses whether an identical code/value pair is appended again
or skipped. Control fields are invalid targets.

### Delete subfield

Delete one subfield code from selected data fields, optionally limited by the
same guided or advanced value matcher. The cataloger explicitly chooses first
matching subfield or every matching subfield. A field left with no subfields
is preserved by default; **Remove the empty field** is an explicit alternative.

### Set indicators

Set indicator 1, indicator 2, or both on selected data fields. **Leave
unchanged** and **MARC blank** are separate values. At least one indicator must
change. Control fields are invalid targets.

### Copy field

Deep-copy selected complete fields to one exact destination tag. Indicators
and ordered subfields are preserved. The destination policy is **Append**,
**Skip if an identical destination field exists**, or **Replace all destination
fields**. Replacement occurs only after at least one source field resolves;
records without a selected source are skipped without deleting anything.
Control-field sources require a control-field destination, and data-field
sources require a data-field destination.

### Move or retag field

Change the tag of selected complete fields while preserving their data,
indicators, and ordered subfields. The fields remain in their source positions
within the record. The existing canonical reorder Quick operation remains the
explicit way to normalize tag order after retagging.
Control fields may be retagged only to another control tag, and data fields only
to another data tag.

### Swap field occurrences

Resolve two single-field selectors against the same exact tag and exchange the
two complete fields' positions in `record.fields`. Field objects, indicators,
and subfields are not reconstructed or exchanged piecemeal. Two canonically
identical selector definitions are a request-level validation error. Distinct
selectors that resolve to the same field in a particular record—for example,
First and Last when only one field matches—skip that record without mutation.
Records missing either requested occurrence are also skipped and reported.

### Remove exact duplicate fields

Within one selected tag, group fields by complete MARC identity: tag, control
value or indicators, and ordered subfield codes and values. Keep either the
first or last field in each duplicate group. Similar fields with different
subfield order, indicators, or values are not duplicates. Unique fields retain
their relative source order.

## Missing, Ambiguous, and Invalid Selections

A syntactically valid selector that does not resolve the requested occurrence
in a record skips only that record. Preview groups skips by bounded reasons,
including:

- no fields passed the filters;
- requested numbered occurrence was absent;
- one side of a swap was absent; and
- both swap selectors resolved to the same field.

The last condition is also surfaced prominently because changing the selector
is required for that record to be eligible. The engine never guesses a nearby
occurrence.

Request-level errors block Preview entirely: invalid tags or subfield codes,
indicator filters on control fields, unsupported occurrence/action
combinations, empty required values, invalid or unsafe regex, incompatible
source/destination tags, and oversized request state.

## Preview and Apply

Preview reports:

- total, changed, unchanged, and skipped record counts;
- fields and subfields affected;
- skipped records grouped by reason;
- representative before/after MARC examples;
- the existing per-tag summary and collapsed per-record diffs; and
- a warning when **Every matching field** changes multiple fields in a record.

The request, selector, and transformation form one canonical immutable value.
Preview records the source store identity, store revision, and, when present,
job file and version identity. Apply rejects a changed source, changed request,
missing preview output, timeout, cancellation, or failed preview.

Preview and Apply call the same transformation entry point. Application writes
to a staged candidate path and adopts it only after complete success. Job-file
work creates the next recoverable file version. Quick Load work retains the
existing snapshot/history behavior. Audit and export metadata identify the
operation kind, selected tag, changed/skipped counts, and bounded reason
counts; they do not store MARC content or raw imported data.

## Component Boundaries

- `marcedit_web/lib/quick_field_selector.py` owns immutable selector values,
  normalization, validation, field resolution, and plain-language selection
  summaries.
- `marcedit_web/lib/quick_field_changes.py` owns immutable operation requests,
  operation validation, one-record transformation, change/skip results, batch
  Preview, and Apply.
- `render/tasks.py` owns only Streamlit controls, session keys, summaries,
  preview rendering, and calls into the engine.
- Existing `transforms` helpers are reused only when their semantics match the
  approved operation exactly. The new engine does not call the task compiler,
  generated Python, AI drafting, or external-task migration.

Selector logic remains independent from rendering, and Preview and Apply share
one transformation entry point.

## Testing Strategy

Table-driven selector tests cover zero, one, two, and more than two same-tag
fields; indicator and subfield filters; case behavior; first, last, every, and
numbered occurrences; control/data restrictions; and bounded invalid input.

Each operation has tests for changed, unchanged, skipped, and invalid records.
Swap tests prove that complete fields exchange source positions, field content
is preserved, same-field resolution does not mutate, extra same-tag fields are
untouched, and missing occurrences produce reason counts. Duplicate tests pin
complete-field identity and stable source order.

Batch tests prove Preview/Apply equivalence, changed/skipped counts, stale
store and stale job-version rejection, cleanup of preview artifacts, atomic
candidate adoption, job-file version creation, Quick Load snapshot behavior,
audit metadata, and bounded representative output. Raw regex tests cover
syntax errors, oversized requests, timeout/cancellation, sandbox failure, and
the current-preview submission gate.

Renderer tests prove operation labels are alphabetical, only compatible
controls appear, summaries describe the exact request, reset clears preview
state, and every-match warnings are visible. Existing Quick batch, Quick
find/replace, task-authoring, import, AI, and authorization suites remain
unchanged and must continue to pass.

## Non-Goals

- Chaining multiple unsaved Quick operations into one Apply.
- Saving a Quick operation as a task from this workflow.
- Templates or cross-field interpolation.
- Institution profiles or conditional Leader/material rules.
- Tag ranges, wildcards, or arbitrary Python.
- Replacing the existing specialized Quick cleanups or Quick find/replace.
- Changing task storage, folder organization, import conversion, AI drafting,
  authentication, deployment, worker, or durable-processing behavior.

## Rollout and Documentation

The feature is additive. The existing Quick operations render and execute
through their current paths. The cataloger operation reference gains a Quick
changes section explaining the one-operation boundary, filter-then-occurrence
selection, skip behavior, swap examples with two 070 fields, and an 856
example selected by `$u` content. Browser acceptance exercises both Quick Load
and a versioned shared-job file before the ticket can be completed.
