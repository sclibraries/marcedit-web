# Jobs and Shared Cataloging

Jobs are shared cataloging workspaces. Use them when a MARC batch needs handoff,
review, or a record of what has already been done before loading records into
FOLIO or another catalog.

Use Quick Load instead when you only need a one-off upload for viewing,
validation, reporting, editing, or conversion.

## Quick Load vs Job Workspace

Home has two starting paths:

- **Quick Load** uploads a `.mrc` file to your default `Personal uploads` job.
  This is the fastest path for one-off work and does not require choosing or
  managing a shared job.
- **Job Workspace** lets you choose or create a named job, then upload a `.mrc`
  file into that selected job.

If you want a file to appear under a named job, upload it from **Home → Job
Workspace → Add a .mrc file to this job**. Uploading from Quick Load will not
attach the file to that named job.

## Creating a Job

1. Open **Home**.
2. Choose **Job Workspace**.
3. Use **Create job** and enter a descriptive name, such as `Vendor load July`
   or `GOBI ebooks 2026-07-08`.
4. The new job becomes the selected job.
5. Use **Add a .mrc file to this job** to attach MARC records to it.

The job then appears on the **Jobs** page.

## Adding Files to an Existing Job

1. Open **Home**.
2. Choose **Job Workspace**.
3. Select the job from the **Job** dropdown.
4. Use **Add a .mrc file to this job**.
5. Open **Jobs**, then open the job to confirm the file appears in **Files**.

The Jobs page shows filename, record count, size, upload time, and whether the
upload is active.

## Sharing a Job

1. Open **Jobs**.
2. Open the job.
3. In **Sharing**, add another cataloger as `editor` or `viewer`.

Roles:

- `owner` can manage sharing, status, notes, and archive/restore.
- `editor` can work the job, change status, and add or resolve review notes.
- `viewer` can inspect files, notes, and activity but cannot change them.

## Review Workflow

Job status is optional and advisory. It helps catalogers coordinate work, but it
does not block editing or export.

Statuses:

- `Active`
- `Needs review`
- `Changes requested`
- `Approved`
- `Ready to load`
- `Complete`
- `Archived`

Typical peer-review flow:

1. A cataloger uploads records and does the batch work.
2. They set the job to **Needs review** and add a status note.
3. Another cataloger opens the job, checks files, activity, validation results,
   and review notes.
4. The reviewer either marks the job **Approved** or **Changes requested**.
5. After the records are loaded, the job can be marked **Complete** or archived.

## Review Notes

Review notes identify specific questions or problems. Notes can be attached to:

- the whole job;
- a record number;
- a control number such as `001` or OCLC number;
- a validation issue;
- a field.

Use notes for things another cataloger needs to see, such as:

- "Please check 856 proxy prefixing."
- "Left duplicate ISBN warning as-is; print/electronic pair is expected."
- "Fixed provider-neutral fields, please confirm."

Open notes appear in the job summary. Resolve a note when the concern has been
handled.

## Activity

The **Activity** section records recent job events such as status changes, note
changes, archive/restore actions, and other job-specific events. Use it to see
what has already happened before continuing another cataloger's work.

## Archive and Restore

Archiving is a soft delete:

- archived jobs disappear from normal active lists;
- uploads, notes, activity, sharing rows, and history remain in the database;
- owners can restore archived jobs;
- the default `Personal uploads` job cannot be archived.

Use archive for completed or stale shared workspaces. Use **Complete** for work
that is done but should still remain visible in active review filters.
