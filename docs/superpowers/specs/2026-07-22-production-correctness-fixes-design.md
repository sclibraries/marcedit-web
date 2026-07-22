# Production Correctness Fixes Design

Date: 2026-07-22

Tickets:
- [TASK-167](../../../.tickets/TASK-167-sqlite-shared-job-attach-compatibility.md)
- [TASK-168](../../../.tickets/TASK-168-task-replace-field-regex-match.md)
- [TASK-169](../../../.tickets/TASK-169-view-marc-field-order.md)
- [TASK-170](../../../.tickets/TASK-170-job-file-count-detail-consistency.md)

## Context

Production runs native Python 3.9 on RHEL 8.10. Its stdlib SQLite rejects
`INSERT ... RETURNING`, which SQLite added in version 3.35.0. Shared-job file
attachment currently uses that syntax after persisting the upload row. The same
syntax also prevents the idempotent legacy-upload migration from materializing
existing uploads as durable job files.

The Jobs list compounds that failure by counting `uploads`, while the opened
job lists non-archived `job_files`. A job can therefore report two files even
when migration produced no visible job-file rows.

The form-built `replace-field-subfield-and-indicators` task is exact-only. The
requested workflow needs an explicit regular-expression match mode without
changing existing saved tasks. Separately, View currently renders the record's
actual MARC directory order. It should preserve that diagnostic truth while
identifying fields that violate the application's ascending-tag convention.

## Isolation and delivery

Implementation uses the dedicated `prod-fixes-task-167-170` linked worktree
and branch, leaving `main`, the active TASK-134 worktree, and existing runtime
artifacts untouched. Each ticket has separate implementation and evidence
commits so the changes can be reviewed or cherry-picked independently before
the complete branch is merged.

Ticket status changes from Todo to In-Progress only after baseline verification
in the isolated worktree. A ticket becomes Completed only after its focused
tests and independent review have no unresolved Critical or Important
findings. The branch is not deployed by this work.

## TASK-167: SQLite-compatible job-file identities

Remove every runtime `INSERT ... RETURNING id` statement from
`marcedit_web/lib/job_files.py`. Execute the same insert without `RETURNING`
and read `cursor.lastrowid` immediately on the same connection. Existing
`BEGIN IMMEDIATE`, savepoint, commit-uncertainty, filesystem cleanup, and
foreign-key behavior remains unchanged.

This scope includes attachment, legacy-upload migration, retained exports, and
new immutable versions. Fixing only the reported attachment would leave the
same production incompatibility in adjacent job-file workflows.

Tests use a connection/cursor wrapper that fails if production code sends SQL
containing `RETURNING`. They exercise a new shared-job attachment and the
idempotent legacy-upload migration. Existing atomicity and uncertain-commit
tests remain the authority for cleanup and recovery behavior.

## TASK-170: Consistent job file counts

`jobs.list_job_summaries()` counts accessible, non-archived `job_files`,
matching the rows returned by `job_files.list_files()` on the detail page. It
does not count legacy `uploads`, removed uploads, or archived job files.

After TASK-167 is deployed and the service restarts, schema initialization
retries the existing idempotent upload-to-job-file migration. The two Routledge
uploads can then materialize as visible job files if their retained upload
artifacts still exist. A missing artifact remains a logged, fail-safe migration
skip, and the corrected card count does not claim that upload as a visible
file. TASK-170 keeps the card and detail page on one visibility definition even
when archive state changes.

Tests cover active rows, archived rows, and a legacy upload that has not yet
materialized. The displayed count must equal the number of default-visible
detail rows.

## TASK-168: Optional regex subfield matching

The existing `replace-field-subfield-and-indicators` operation gains two
additive parameters:

- `regex`, default `false`, exposed as **Treat match value as regex**;
- `ignore_case`, default `false`, exposed as **Case-insensitive**.

With `regex=false`, matching remains the current case-sensitive equality test.
Existing saved operation markers omit the new keys and therefore retain exact
behavior. With `regex=true`, the match value is compiled once and matched with
`re.search` against the complete selected subfield value. `ignore_case=true`
adds `re.IGNORECASE` in regex mode. Replacement behavior is unchanged: every
matching occurrence of the selected subfield in a matching field is replaced
as a complete value, and the field's indicators are updated when at least one
subfield matched.

The form builder validates an enabled regex during task rendering/saving.
Invalid patterns raise a cataloger-readable `ValueError` before the task is
persisted or any record is processed. The transform helper also compiles before
iterating fields, so direct callers cannot partially mutate a record on an
invalid pattern.

Tests cover legacy exact matching, regex substring matching such as `TFeba`,
case-sensitive and case-insensitive behavior, invalid patterns, multiple
matching subfields, generated code, and old/new marker round trips.

## TASK-169: Preserve and validate MARC field order

View continues to render the record's actual directory order and does not sort
or mutate it. This preserves evidence about the loaded file rather than hiding
an upstream ordering problem.

A pure viewer helper inspects `record.fields` and returns bounded adjacent tag
inversions under the application's ascending alphanumeric tag convention.
Repeated tags are valid. An inversion occurs when a later adjacent tag sorts
before the previous tag, for example `040` followed by `035`. View displays a
warning containing a bounded number of those transitions and explains that the
displayed order is the source order. The warning is diagnostic only.

Tests use records containing leader, control fields, repeated fields, 035, and
surrounding data fields. They prove canonical input produces no warning, an
out-of-order 035 produces the expected inversion, repeated tags do not warn,
diagnostics are bounded, and rendered text preserves the original order byte
for byte.

## Verification and review

Each ticket follows test-driven development: add the smallest regression,
observe the intended failure, implement the minimum fix, and rerun the focused
suite. After all four tickets:

1. run the combined focused suites for jobs, job files, migrations, tasks,
   transforms, viewer, and View rendering;
2. run compile and whitespace checks;
3. run the complete suite in the supported Python 3.9 container and report
   every skip by name and reason;
4. request independent review of each ticket and a final whole-branch review;
5. record exact evidence in each ticket before changing its status to
   Completed.

Production deployment, direct production database edits, and automatic MARC
field sorting are explicitly out of scope.
