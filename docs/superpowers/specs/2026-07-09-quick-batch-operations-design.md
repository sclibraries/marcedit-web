# Quick batch operations - design spec

**Date:** 2026-07-09
**Ticket:** TASK-137 (`.tickets/TASK-137-quick-batch-operations.md`)

## Problem

The Tasks page can already run saved task files and has a one-shot quick
find/replace tool. Some cataloging cleanup work is common enough, structured
enough, and safe enough that catalogers should not need to author a saved task
or write Python. These operations should be fast, constrained by valid MARC
codes where possible, previewable, and intentionally unconditional.

The first approved group excludes FOLIO container code standardization in
`035 $9`. That workflow is important, but it has its own local controlled code
list and "always replace" semantics, so it belongs in a separate ticket/design.

## Design

Add a **Quick batch operations** section on the Tasks page, near the existing
quick find/replace tool. These operations are not saved tasks and do not create
task files. They operate on the currently loaded batch, produce a preview, and
then apply the selected change to the full batch after confirmation.

The first operation families:

- **Leader value setter**
  - Expose safe positions only: `05`, `06`, `07`, `08`, `17`, `18`, `19`.
  - Position dropdown controls the valid value dropdown.
  - Applies the selected value to every record.
  - Exclude generated or structural leader positions: `00-04`, `09`, `10-16`,
    `20-23`.

- **008 Form of item**
  - Dropdown for valid form-of-item values.
  - Use Leader/06 and Leader/07 to choose the correct 008 byte where possible,
    matching the existing `set_008_form_of_item` logic.
  - Skip records where 008 is missing or no safe position can be determined,
    and report skipped counts in preview/results.

- **040 cleanup**
  - Ensure `$e rda`.
  - Ensure local `$d <code>` using a constrained text input or dropdown for
    the local agency code.
  - Avoid duplicate `$e rda` and duplicate `$d` values.

- **856 URL tools**
  - Add a proxy prefix to unproxied matching URLs.
  - Remove the proxy prefix from proxied URLs.
  - Delete 856 fields whose `$u` contains selected text/domain.
  - Preview matching fields/records before applying.

- **035/OCLC cleanup**
  - Normalize OCLC 035 values to canonical `(OCoLC)` form.
  - Remove duplicate OCLC 035 values.
  - Do not touch `035 $9` container codes.

- **Local 9xx cleanup**
  - Delete an exact 9xx tag or a safe range such as `9XX`.
  - Preview counts by tag before applying because local fields are
    institution-specific.

- **655 genre/form cleanup**
  - Add a standard 655 field if absent.
  - Delete 655 fields matching selected unwanted text.
  - Preview required because this operation is text/meaning-sensitive.

## Architecture

Implement this as deterministic application code, not generated Python task
files.

Add a small operation layer under `marcedit_web/lib`, likely
`quick_batch.py`, with:

- request dataclasses for each operation family;
- preview functions that inspect a `RecordStore`/record iterable and return
  counts plus short examples;
- apply functions that mutate records and return result counts;
- validation helpers for coded values and user-supplied text.

The Tasks page renders the operation selector and delegates preview/apply work
to this library. Apply should reuse the existing loaded-batch replacement path
and task-run result/diff presentation where practical, so catalogers can review
what changed without downloading immediately.

## Data Flow

1. Cataloger selects an operation family.
2. UI renders the operation-specific controls.
3. Preview reads the loaded batch and reports affected/skipped records.
4. Cataloger confirms apply.
5. Apply mutates a copy or replacement stream of the loaded records.
6. The current loaded batch is replaced with the transformed output.
7. Results show changed/skipped counts and any warnings.

Operations apply to the whole loaded batch. There is no conditional mode in
this quick path. If a cataloger needs exceptions, filters, or conditional
matching beyond the operation's built-in safe matching, they use the task
builder/code path.

## Error Handling

- No loaded batch: show the same style of "upload a file first" message used
  elsewhere on Tasks.
- Invalid request: block preview/apply with a clear validation message.
- Missing required field in a record: skip that record where appropriate and
  report the skipped count; do not crash the operation.
- Ambiguous/destructive operations, especially 9xx/655/856 deletes: require
  preview before apply.
- Generated MARC structural positions remain out of scope; the writer manages
  lengths and base addresses.

## Testing

Unit tests should cover each operation family in `tests/test_quick_batch.py`:

- valid value lists and validation errors;
- preview counts for affected/skipped records;
- apply behavior on representative MARC records;
- "does not touch `035 $9`" for OCLC cleanup;
- duplicate prevention for 040 cleanup;
- safe skip behavior for missing 008/856/655 fields.

Render tests should cover the Tasks-page integration at a high level:

- operation selector appears when a batch is loaded;
- preview is required before apply;
- apply updates the loaded batch through the established session path;
- no saved task row/file is created by these one-shot operations.

Full verification should include the relevant unit/render tests plus the
project pytest suite in the Python 3.9 container.

## Out of Scope

- FOLIO container code standardization in `035 $9`.
- Conditional quick operations.
- Saved presets.
- Editing generated MARC leader structure positions.
- Importing or managing the full local container-code table.
