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
available through their existing execution engines. Their presentation is
consolidated with the focused field changes under one operation selector.

## Cataloger Workflow

Quick changes presents one alphabetized **Quick operation** dropdown. It is
the only operation selector on the page and contains:

- Find and replace;
- every existing specialized operation: 008 form of item, 040 cleanup, 655
  genre/form cleanup, 856 URL tools, Leader value, Local 9xx cleanup, OCLC 035
  cleanup, and Reorder fields by canonical tag order; and
- every focused field change: Add field, Add subfield, Copy field, Delete
  field, Delete subfield, Move or retag field, Remove exact duplicate fields,
  Set indicators, and Swap field occurrences.

The complete list is sorted by its cataloger-facing label, irrespective of
which execution engine owns an operation. Selecting an entry shows only that
operation's relevant controls. Find and replace is no longer an always-visible
form above the dropdown, and specialized operations do not render a second,
nested selector.

The cataloger chooses exactly one operation, completes its controls, reads a
plain-language summary, previews the loaded batch, and applies only from a
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

Each match value or raw expression retains the existing 1,024-character and
2,048-byte limit. The complete canonical structured-adapter payload is bounded
separately to 65,536 characters and 131,072 bytes so the approved 100-row Add
field request remains representable. Exceeding either boundary blocks Preview.

Control fields reject indicator and subfield filters. Leader `000` is not a
field selector target; existing Leader Quick controls remain authoritative.
The selector is a pure library component with no Streamlit, database, session,
or file dependency, so validation, preview, and application use identical
selection semantics.

### Operation and Occurrence Compatibility

Target filters and occurrence choice are orthogonal except where this table
states otherwise. The renderer derives its occurrence choices from this table;
it does not infer support from whichever controls happen to be visible.

| Operation | First | Last | Numbered | Every | No occurrence selector |
| --- | --- | --- | --- | --- | --- |
| Add field | — | — | — | — | Required; record scope is explicit |
| Add subfield | Yes | Yes | Yes | Yes | — |
| Copy field | Yes | Yes | Yes | Yes | — |
| Delete field | Yes | Yes | Yes | Yes | — |
| Delete subfield | Yes | Yes | Yes | Yes | — |
| Move or retag field | Yes | Yes | Yes | Yes | — |
| Remove exact duplicate fields | — | — | — | — | Required; all filtered fields form the candidate set |
| Set indicators | Yes | Yes | Yes | Yes | — |
| Swap field occurrences | Yes | Yes | Yes | No | Two single-field selectors are required |

Swap's two selectors share only the exact tag. Their indicator filters,
subfield filters, value modes, case choices, and occurrences may differ. This
allows a cataloger to distinguish two same-tag fields by content as well as by
position. Canonically identical complete selector definitions are invalid;
different selectors that happen to resolve to the same field in one record
produce the bounded same-field skip reason.

### Advanced Regular Expressions

Guided matching is the default. A collapsed **Advanced: regular expression**
choice changes only the optional subfield-value matcher to raw regex. It is
never required for ordinary selection.

Raw regex requests reuse the existing bounded canonical-request and sandbox
execution contract. They never compile or execute in the Streamlit process.
Syntax errors, validation timeouts, cancellations, oversized
requests, and sandbox failures block Preview with bounded cataloger-facing
errors. Apply additionally requires a current successful preview of the exact
canonical request and source revision.

This safety boundary applies to the complete Common field changes request, not
only to its regex matcher. Preview preparation and Apply preparation both call
the same fixed quick-change adapter in the subprocess. The adapter deserializes
the canonical request and invokes the same one-record transformation entry
point. It does not compile a task, accept generated Python, or dispatch through
the saved-task operation palette.

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

### Unified Selection and Preview Lifecycle

The top-level Quick operation value is presentation state, not part of any
engine's immutable request. It routes to exactly one of three existing
boundaries:

- Find and replace continues to build and apply `BatchReplaceRequest` values;
- focused field changes continue to build and apply
  `QuickFieldChangeRequest` values through the structured sandbox adapter; and
- specialized cleanups continue to build and apply `QuickBatchRequest` values.

The routing layer never translates one request type into another. Existing
validation, preview identity, sandboxing, staged adoption, and audit behavior
remain owned by the selected engine.

Whenever the selected operation label changes, the page cleans preview
artifacts and export-ready state for all three Quick engines before rendering
the new controls. This applies when switching between engines and between two
operations owned by the same engine. Harmless keyed form values may remain so
returning to an operation does not force re-entry, but no prior preview may
become current or applicable under a different selection.

Every widget key is distinct from every stored domain-object key. In
particular, the focused field-change Preview button uses a dedicated button
key and never shares `quick_field_change_preview`, which is reserved for the
`QuickFieldChangePreview` object. This addresses the observed failure where
Streamlit stored a Boolean button value under the preview-object key and the
renderer then attempted `preview.error` on that Boolean.

### Execution Precedent

The feature deliberately combines two existing, tested boundaries:

- it follows `quick_batch.py` for immutable request/preview/result values,
  source and job-version identity, stale-preview rejection, and staged
  adoption; and
- it follows `batch_replace.py` for bounded subprocess transformation of MARC
  input before the parent process accepts an output artifact.

Unlike `batch_replace.py`, it does not translate the request into a
`task_builder.Operation` and does not call `render_ops_to_python`. The child
invokes a fixed adapter whose only variable input is the validated canonical
request. Both Preview and Apply use that adapter; Apply reruns it against the
current complete source and verifies source identity and output record count
before adoption.

The sandbox request envelope gains a mutually exclusive structured-adapter
mode: an allowlisted adapter identifier plus a JSON value. Existing task-body
execution remains unchanged. The child rejects an unknown adapter, a request
that supplies both adapter data and a task body, or a payload that fails the
adapter's validation. The `quick-field-change` adapter is selected by a fixed
allowlist in the child; no operation name is resolved as a Python symbol and
no payload value is passed to `exec`.

## Component Boundaries

- `marcedit_web/lib/quick_field_selector.py` owns immutable selector values,
  normalization, validation, field resolution, and plain-language selection
  summaries.
- `marcedit_web/lib/quick_field_changes.py` owns immutable operation requests,
  operation validation, one-record transformation, and change/skip results. It
  has no Streamlit dependency.
- `marcedit_web/lib/quick_field_change_runner.py` owns canonical request
  serialization, the fixed sandbox adapter call, batch Preview and Apply,
  staged artifacts, stale-state checks, and bounded subprocess diagnostics.
- `marcedit_web/lib/sandbox.py` owns the generic mutually exclusive adapter
  envelope and the fixed child-side adapter allowlist; it contains no Quick
  operation semantics.
- `marcedit_web/render/quick_field_changes.py` owns the new operation and
  selector controls, distinct widget/domain-object session keys,
  plain-language summaries, preview evidence, and reset behavior. It accepts
  the focused operation selected by the parent and does not render a nested
  operation dropdown.
- `render/tasks.py` owns the small unified Quick-operation registry and router
  because the existing Find/Replace and specialized Quick renderers already
  live there. It passes the selected focused operation and existing
  loaded-file, job-version, audit, and export context to the dedicated
  renderer; it does not absorb the focused operation controls or semantics.
- Existing `transforms` helpers are reused only for the exact semantic subsets
  listed below. The new engine does not call the task compiler, generated
  Python, AI drafting, or external-task migration.

The operation request is serialized as bounded canonical JSON in the
structured-adapter envelope. No user value is interpolated as executable
source. The child adapter validates the deserialized value again before
calling the one-record transformation.

### Existing Semantic Equivalents

Selector-aware behavior remains owned by the new engine. Existing helpers are
called only for these equivalent subsets, and each shared subset receives an
equivalence test against the corresponding saved-task operation:

| Quick operation | Existing helper | Exact shared subset |
| --- | --- | --- |
| Add field | `make_field`, `add_field_if_absent` | Data-field construction and data-field skip-if-identical only; control-field construction and record scope remain Quick-owned |
| Add subfield | `add_subfield_to_fields` | Every occurrence with no field filter; focused subsets use the same subfield insertion primitive directly |
| Copy field | `copy_field` | Every occurrence with no field filter and Append destination policy |
| Delete field | `delete_tags`, `delete_fields_matching_predicate` | All-fields exact-tag deletion or predicate identity only; occurrence resolution remains Quick-owned |
| Delete subfield | `delete_subfields`, `delete_subfields_matching_value` | Every subfield of a code, plus Exact/Contains/raw-regex value subsets; Starts with, Ends with, and first-subfield selection remain Quick-owned |
| Move or retag field | `move_field` | Complete-field retag semantics for the all-fields, unfiltered subset |
| Set indicators | `set_indicators` | Indicator replacement for the all-fields, unfiltered subset |
| Remove exact duplicate fields | None | New complete-field identity and stable-order semantics |
| Swap field occurrences | None | New identity-based position exchange semantics |

Where a helper only accepts a whole tag, the engine must not call it after
resolving a smaller occurrence subset. It performs the same primitive mutation
on the resolved field objects and the equivalence test pins the overlapping
result. This avoids widening First, Last, or Numbered into Every.

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
audit metadata, output record-count verification, and bounded representative
output. Raw regex tests prove the expression never compiles or executes in the
Streamlit process and cover syntax errors, oversized requests,
timeout/cancellation, sandbox failure, and the current-preview submission gate.
Sandbox contract tests prove adapter/body mutual exclusion, unknown-adapter
rejection, second validation in the child, and unchanged legacy task-body
execution.

Table-driven compatibility tests cover every cell in the operation/occurrence
matrix, including rejected Every-selection for Swap. Equivalence tests cover
each overlapping helper subset in the component table and prove that focused
occurrence selection never mutates unselected fields.

Renderer tests prove the unified registry contains Find and replace, all nine
focused operations, and all eight specialized operations exactly once; labels
are alphabetical; only the selected operation's controls appear; no nested
operation dropdown is rendered; summaries describe the exact request; reset
clears preview state; and every-match warnings are visible. A stateful
Streamlit test double writes button values into keyed session state and proves
that an initial render cannot replace the focused preview object or raise at
`preview.error`. Operation-switch tests prove prior preview artifacts are
cleaned and cannot be applied after the switch. Existing execution, task-
authoring, import, AI, and authorization suites remain unchanged and must
continue to pass.

## Non-Goals

- Chaining multiple unsaved Quick operations into one Apply.
- Saving a Quick operation as a task from this workflow.
- Templates or cross-field interpolation.
- Institution profiles or conditional Leader/material rules.
- Tag ranges, wildcards, or arbitrary Python.
- Replacing or unifying the three existing Quick execution engines. The
  dropdown unifies selection and layout only.
- Adding any Common field change to `OPERATIONS_PALETTE`, the AI draft schema,
  or the Gemini prompt. Quick operations are not saved-task operations.
- Changing task storage, folder organization, import conversion, AI drafting,
  authentication, deployment, worker, or durable-processing behavior.

## Rollout and Documentation

The feature preserves the existing Quick execution engines while replacing
their separate entry-point controls with the unified selector. The cataloger
operation reference gains a Quick changes section explaining the one-operation
boundary, filter-then-occurrence selection, skip behavior, swap examples with
two 070 fields, and an 856 example selected by `$u` content. Browser acceptance
exercises both Quick Load and a versioned shared-job file before the ticket can
be completed.
