# Job File Work Items Design

Ticket: [TASK-150](../../../.tickets/TASK-150-job-detail-file-attachment-workflow.md)

Date: 2026-07-14

## Purpose

Make a job a durable shared cataloging project that can contain multiple MARC
files at different workflow stages. Each file must have its own checkout,
versions, review state, notes, and labeled exports. Catalogers should be able to
complete the workflow from the job detail page without returning to Home merely
to attach another file.

The motivating workflow is one long-lived Routledge job containing an existing
catalog deletion file, a fresh vendor delivery, and later supplemental files.
Each file is processed and reviewed independently, while sharing the same job,
collaborators, and overall context.

## Current Problem

Home's Job Workspace is the only place that can attach a `.mrc` file to a job.
The Jobs detail page lists and loads files but has no uploader. This is a missing
capability, not a navigation-state defect.

The deeper data model also treats important mutation history as job-scoped.
`job_snapshots` identifies a job but not the specific uploaded file. Once a job
contains several active work files, histories and derived outputs can be
ambiguous. Saved-task output is retained as a snapshot/export but does not
become the file's current working state.

## Design Principles

- A job is the shared project; a job file is the unit of work.
- One operation acts on one file at a time.
- The original upload and every accepted version are immutable.
- The current version changes only through an atomic, validated pointer swap.
- Every mutation requires an exclusive file checkout and a matching version.
- Review, history, and exports always identify one file and one exact version.
- Failed work never changes the current version.
- Existing data is migrated conservatively; ambiguous history is never guessed
  onto a file.

## Domain Model

### Job

A job continues to own:

- name and description;
- owner and shared access roles;
- overall human-controlled status;
- job-level notes and aggregate activity;
- archive state.

The job status is not automatically derived from file statuses. A Routledge job
may remain active while one file is complete and another needs review.

### Job File

A job file is an independent work item with:

- job id;
- display name and optional description;
- workflow status;
- immutable original upload reference;
- current version id;
- created/updated identity and timestamps.

File statuses are:

`new`, `in_progress`, `needs_review`, `changes_requested`, `approved`,
`exported`, and `complete`.

Attaching a later Routledge delivery creates a new job file. It does not replace
or mutate any earlier job file.

### File Version

Each accepted mutation creates one immutable file version containing:

- job file id;
- monotonic per-file version number;
- optional parent version id;
- durable MRC path;
- record and byte counts;
- author and creation time;
- source kind such as `original`, `record-edit`, `task`, `quick-batch`,
  `quick-replace`, `folio-fix`, or `restore`;
- operation/task label and bounded summary data;
- validation and diff summary metadata when available.

Version 1 is the original upload. Applying a valid operation writes a candidate
file, verifies it, inserts the version row, and atomically changes the job
file's current-version pointer. Rollback creates a new version derived from the
selected historical version; it does not rewrite or delete history.

### File Export

An export is an immutable artifact generated from one exact file version. It
stores:

- job file and source version ids;
- purpose, for example `EDS deletion load`, `EDS replacement load`, or
  `FOLIO import`;
- optional description and external load identifier;
- output filename and durable path;
- creator, timestamp, record count, and validation summary;
- state: `draft`, `ready`, `superseded`, or `loaded`;
- loaded destination, timestamp, and note when confirmed manually.

An export from an unapproved version is `draft`. An export from the approved
current version is `ready`. Creating a later current version makes existing
non-loaded exports from older versions `superseded`; it never deletes them.
Marking an export `loaded` is a manual audit action in this phase.

Creating any export requires the file checkout and a final current-version
comparison. Marking an existing export `loaded` does not require checkout, but
does require owner/editor access and records the actor.

## Storage Changes

Add three durable entities:

1. `job_files` for the logical work item and current-version pointer.
2. `job_file_versions` for immutable MARC versions.
3. `job_file_exports` for retained, labeled delivery artifacts.

The existing `uploads` row remains ingestion provenance and is referenced by
the job file's original version. Review notes gain optional structured foreign
keys for job file, version, and export while preserving existing free-form
anchors for legacy notes.

New snapshot creation moves to file versions. Existing `job_snapshots` remain
readable as legacy history during migration. The implementation must not keep
two writable history systems after all mutation paths have moved to file
versions.

## Checkout and Concurrency

All file mutations use one exclusive `job-file` advisory-lock resource keyed by
job-file id. Owners and editors may acquire or renew it; viewers may not.

While a file is checked out:

- everyone may view the file, history, diffs, notes, and exports;
- only the holder may edit, run/apply tasks, run/apply batch operations,
  restore, change file state through a mutation, or create an export;
- every save/apply compares the opened current-version id with the database's
  current-version id immediately before committing;
- a mismatch or lost/expired checkout fails visibly and preserves the current
  version.

The lease shows its holder and expiry, renews during active work, and releases
on **Done**, **Return for review**, or expiry. Owners/admins may force-release
with explicit confirmation and an audit event.

This newer decision supersedes the named-job lock scope in
`docs/adr-collaboration-locking.md`, which proposed record locks for normal
edits and a whole-job lock for batch mutations. File work items require one
exclusive file checkout for every mutation so separate files in the same job
can progress concurrently without allowing conflicting changes within one
file. The implementation must update or supersede that ADR explicitly.

## Permissions and Approval

- **Owner:** manage sharing and job archive state; perform editor actions;
  force-release abandoned file checkouts.
- **Editor:** attach files; check out and mutate one file; create versions,
  notes, approvals, and exports.
- **Viewer:** inspect jobs, files, versions, diffs, validation, notes, and
  exports without mutating them.

Approval records the approved version and approver. Approval by the version's
author is labeled `self-approved`; approval by another cataloger is labeled
`peer-approved`. Both are allowed. Creating a later version makes the prior
approval historical and moves the file back to `in_progress`.

### File Status Transitions

- Attachment creates the file as `new`.
- Checkout or the first accepted mutation moves `new` to `in_progress`.
- **Return for review** releases checkout and sets `needs_review`.
- An editor reviewing the current version may set `changes_requested`, which
  releases any reviewer checkout; the next editing checkout sets
  `in_progress`.
- Approval of the exact current version sets `approved` and records self/peer
  approval.
- Creating a ready export from that approved version sets `exported`.
- Marking an export loaded records the artifact state but does not implicitly
  complete the file; owner/editor explicitly sets `complete` when the workflow
  is finished.
- Creating any later current version invalidates the active approval, marks
  older non-loaded exports `superseded`, and sets `in_progress`.

Every transition is recorded in both file activity and the job's aggregate
activity stream with file identity, actor, and timestamp.

## User Experience

### Job Detail

The Files section becomes the primary entry point and includes:

- **Attach MARC file** for owners/editors;
- one row per job file with name, status, current version, records, last editor,
  and updated time;
- actions to open, view history, review exports, or remove/archive the file.

Home may retain its Job Workspace uploader as a shortcut, but it must call the
same attachment service and create the same job-file/version records.

### File Context

Opening a file establishes an explicit context across View, Validate, Report,
MarcEditor, Tasks, History, and export screens:

`Job -> Job File -> Current Version`

Session state may cache these identifiers for navigation, but database rows are
the authority. Refresh restores the exact file and current version after
re-checking access.

### Processing

The cataloger checks out one file before mutation. Quick operations retain
preview/apply. Saved tasks become a two-stage flow:

1. Run against the opened version and review errors/diff.
2. **Apply as new version** after a successful result and stale-version check.

Applying makes the output the current working version. A run that is not
applied may be discarded or retained as a bounded temporary preview, but it is
not presented as accepted file history.

### Review

Reviewers can open the current version, compare it with its parent, inspect
validation, and add file/version-specific notes. They may request changes or
approve the current version. Another editor can then check out the file, create
a correcting version, and return it for review.

### Export

The export form requires a purpose and optional description. The file page
lists every export with its source version and state. Draft and superseded
artifacts remain visibly distinct from ready-to-load artifacts.

## Atomicity and Failure Handling

- Stream uploads to a temporary destination, validate/index them, then create
  the job file and original version in one database transaction. Cleanup the
  temporary file if any step fails.
- Write task/edit/batch candidates to a new path. Validate record counts and
  operation-specific invariants before inserting a version.
- Insert the version and compare/swap the current-version pointer inside one
  immediate transaction while re-checking checkout ownership.
- If candidate generation, validation, checkout, version comparison, database
  write, or file adoption fails, retain the previous current version and remove
  the unreferenced candidate.
- Create an export row only after its file is fully written and verified.
- Never silently reuse an export after its source version is no longer current.

## Migration

For every existing non-removed upload attached to a job:

1. Create one job file.
2. Copy the existing durable upload bytes into immutable version storage and
   create version 1 referencing that copy. The migration must not leave the
   original version on a path that current mutation code can overwrite.
3. Set version 1 as current.
4. Preserve upload ownership, timestamps, filename, counts, and access through
   the parent job.

Associate an existing snapshot with a job file only when the relationship is
deterministic from durable provenance. Snapshots that cannot be linked without
guessing remain under a **Legacy job history** section. Existing job sharing,
statuses, notes, and archive state remain unchanged.

The migration is idempotent and covered by upgrade tests. It must be safe to
restart after partial completion.

## Non-Goals

- Simultaneous editing of one file or record-level parallel editing within a
  file.
- One task or batch operation spanning multiple files.
- Direct EDS or FOLIO API submission.
- Automatic job-status derivation from file states.
- Deleting historical versions or loaded export evidence through normal file
  cleanup.

## Testing and Acceptance

Intent-focused tests must cover:

- attaching multiple files to one job from Jobs and Home;
- completely separate current versions, histories, notes, and exports per file;
- file checkout acquisition, renewal, release, expiry, and audited force-release;
- owner/editor/viewer enforcement;
- stale-version and lost-checkout rejection for every mutation path;
- successful record edit, task apply, quick batch, quick replace, FOLIO fix,
  and restore creating a new current version;
- failed/partial operations preserving the prior current version;
- self-approval and peer approval tied to exact versions;
- draft, ready, superseded, and loaded export transitions;
- refresh and cross-cataloger handoff restoring the authoritative file/version;
- idempotent migration and explicit legacy-history fallback;
- no whole-file bytes or parsed-record lists retained in session state.

The end-to-end acceptance scenario is:

1. Create or open `Routledge load`.
2. Attach an existing-catalog file and a fresh-vendor file.
3. Invite another cataloger.
4. Check out the existing-catalog file, set Leader/05 to `Deleted`, apply as a
   new version, approve it, and create a ready `EDS deletion load` export.
5. Check out the fresh-vendor file independently, run and apply a cleanup task,
   return it for review, approve it, and create a ready `EDS replacement load`
   export.
6. Verify both files retain independent versions, diffs, notes, statuses, and
   exports and that a second cataloger can continue either handoff after a new
   session or browser refresh.

## Considered Alternatives

### Minimal Jobs uploader

Adding only a file uploader to Jobs leaves snapshots and outputs job-scoped and
ambiguous. It does not satisfy multi-file review and was rejected.

### Child job per file

Creating a child job for every file isolates history but duplicates sharing,
notes, and navigation and conflicts with the approved mental model of one
multi-part Routledge project. It was rejected.
