# Jobs and Shared Cataloging

Jobs are shared workspaces for MARC files that need handoff, review, or a record
of what happened before loading records into FOLIO, EDS, or another system. A
job can contain multiple related files, and each file is an independent work
item.

## Quick start

1. Create or open a job and attach one or more related `.mrc` files.
2. Check out one file before changing it. Only one cataloger edits that file at
   a time.
3. Run edits or tasks, review the result, and create a retained export for the
   external load.
4. Return the file for review, add notes when needed, and update the job's
   handoff status.

## Job, file, and export

- A **job** is the shared project. It holds the people, overall status, review
  notes, activity, and all related files.
- A **file** is one work item inside the job. Each file has its own checkout,
  current version, history, workflow state, approval context, and exports.
- A **retained export** is a saved copy of one exact file version prepared for
  an external load. Marking it loaded records the destination; it does not
  automatically complete the file or job.

## Quick Load or a shared Job?

Use **Quick Load** for one-off viewing, validation, reporting, editing, or
conversion. Quick Load places the upload in your Personal uploads workspace.

Use a named **Job** when files need to be shared, checked out, reviewed,
processed in stages, or kept together as one recurring project.

## Create or open a job

Use Home's Job Workspace to create a named job, or open an existing job from
Jobs. Give recurring work a stable descriptive name such as `Monthly vendor
load`; dates and stages belong on the individual files and exports.

## Attach related files

Open the job and use **Attach MARC file**. Attaching a later delivery creates a
second file in the same job; it does not replace the earlier file. Owners and
editors can attach files. Viewers can inspect files but cannot attach or change
them.

## Check out, edit, and return a file

Owners and editors check out a file before editing, applying a task, running a
batch operation, restoring a version, or creating an export. Other catalogers
may inspect the file while it is checked out, but only the checkout holder can
change it. When finished, choose **Done** or **Return for review** so another
cataloger can check it out.

Each accepted change creates a new immutable version. History identifies who
made the version and what operation created it. Restoring an older result
creates a new current version; it does not erase later history.

## Create and record exports

Create a retained export from the exact version you intend to load. Give it a
clear purpose such as `Deletion load` or `Replacement load`. Download that
artifact for the external system, then use **Mark loaded** to record its
destination and optional external identifier. The retained artifact remains
with the file for later review.

## Invite catalogers

Open the **People** tab. Owners can grant or revoke access:

- **Owner** manages people, job status, notes, and archive or restore actions,
  and can perform editor work.
- **Editor** can attach, check out, edit, review, and export files and can add
  or resolve review notes.
- **Viewer** can inspect files, notes, people, and activity without making
  changes.

## Review and handoff

Use **Next handoff** for the job's overall advisory status and an optional
handoff note. Each file keeps its own workflow state, so one file may be
complete while another still needs review. Use Review notes for questions that
another cataloger must address, and resolve a note when the concern is handled.

## Recurring vendor load example

Use one long-lived vendor job for the related round trip:

1. Attach the current catalog extract or deletion file as the first file.
2. Check it out, run the deletion edit, review it, and create a labeled retained
   export for the external system. Mark that export loaded after the load.
3. Attach the fresh vendor delivery as a second file in the same job.
4. Check out the fresh file, run the saved vendor task, review the new version,
   and create the replacement export.
5. Return either file for review or complete it independently. The job keeps the
   shared people, notes, and activity together across both stages.

## Complete, archive, or restore

Use **Complete** when the work is finished but should remain visible with active
jobs. Owners may archive a completed or stale job from Settings; archiving is a
soft delete that retains files, history, notes, people, and activity. Owners can
show archived jobs and restore one later. Personal uploads cannot be archived.
