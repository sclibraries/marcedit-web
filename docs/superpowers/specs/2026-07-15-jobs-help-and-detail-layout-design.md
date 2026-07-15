# Jobs Help and Detail Layout Design

Ticket: [TASK-152](../../../.tickets/TASK-152-jobs-help-and-detail-layout.md)

Date: 2026-07-15

## Purpose

Make Jobs easier for catalogers to understand and use without changing the
collaboration model. An opened job should behave as a file-first shared
workspace: its MARC files and current handoff state remain prominent, while
review, sharing, activity, and administrative controls remain available without
forming one long stacked page.

The Jobs screen will also provide a simple, in-application guide explaining how
a job can contain multiple related files and work stages. The worked example is
a generic recurring vendor load rather than a vendor-specific procedure.

## Approved Scope

- Keep the Jobs list substantially unchanged.
- Add a discoverable **How jobs work** control to the Jobs list and detail
  views.
- Reorganize only the opened-job detail view.
- Keep Files and the current job handoff visible above secondary content.
- Move Review notes, People, Activity, and Settings into tabs.
- Rewrite `docs/jobs.md` as a practical cataloger guide and use it as the full
  in-application help source.
- Preserve all existing permissions, persistence, checkout, version, export,
  status, review-note, sharing, activity, and archive behavior.

This work does not add new workflow states, database tables, automatic routing,
notifications, simultaneous editing, or a new Help page in global navigation.

## Current Problem

The opened-job page always renders these sections vertically:

1. Status
2. Files
3. Sharing
4. Review notes
5. Activity
6. Archive or restore

The model is complete, but the presentation makes routine file work require
scrolling past unrelated controls. It also gives status, sharing, review, and
administration the same visual weight as the files that catalogers actually
process.

The existing Jobs documentation explains concepts but still directs users to
Home to attach files. The current application can attach files directly from an
opened job and supports independent file checkout, versions, states, review,
and retained exports. Help must describe that current behavior.

## Information Architecture

### Jobs List

Retain the existing list cards, archived toggle, summary counts, and Open
action. Add **How jobs work** beside the Jobs heading so help is visible before
a cataloger chooses a job.

No new list filters, dashboards, job-creation form, or table redesign are part
of this ticket. The scrolling problem is in the opened-job detail view.

### Opened Job Header

Use one compact header area containing:

- Back to jobs
- job name
- current job status
- the signed-in cataloger's role
- owner identity
- **How jobs work**

This preserves context without creating a separate Status section above the
files.

### Primary Workspace

Render a responsive top row with:

- a wide **Files** area containing attachment and the existing file table;
- a narrower **Next handoff** area containing the current job workflow status,
  optional status note, and update action.

Files are the primary content and remain visible regardless of which secondary
tab is selected. On a narrow viewport, Streamlit may stack the two columns;
Files remains first.

For users who cannot edit the job, Next handoff shows the current status without
mutation controls. Archived/inactive behavior remains unchanged.

### Secondary Tabs

Render four tabs below the primary workspace:

1. **Review notes** — existing notes, resolve actions, and note creation.
2. **People** — existing access list and owner-only grant/revoke controls.
3. **Activity** — the existing recent job activity stream.
4. **Settings** — archive or restore controls when currently allowed.

The tab names use cataloger-facing language. **People** replaces the more
technical **Sharing** heading; the underlying access roles and services do not
change. Settings may show an explanatory caption when no administrative action
is available, avoiding an apparently broken empty tab.

Streamlit tabs are used for information organization, not lazy loading. This
ticket does not claim a server-memory or computation reduction from the visual
change.

## Help Experience

**How jobs work** opens a large dialog over the current screen. The cataloger
does not navigate away from the list or opened job and therefore does not lose
their place.

The canonical guide begins with a compact quick start, so the dialog presents
these steps first without maintaining a second prose copy in Python:

1. Attach one or more related MARC files to the job.
2. Check out a file before changing it; only one cataloger edits that file at a
   time.
3. Run edits or tasks, then create a retained export for the external load.
4. Return the file for review, add notes when needed, and update the handoff
   status.

The remainder of that same file provides the fuller guide. `docs/jobs.md` is the
canonical help copy; the application must not maintain a second full prose copy
that can drift.

The Docker image currently omits `docs/`. Because private Docker deployments
must be able to open the guide, the image will copy `docs/jobs.md` to the same
repository-relative location. Native deployments already run from the project
root. A missing or unreadable guide must fail visibly in the dialog with a short
message; it must not break the Jobs page.

## Guide Content

Rewrite `docs/jobs.md` in plain cataloger language with these sections:

- What a job is
- Quick start
- Quick Load versus a shared Job
- Create or open a job
- Attach multiple related files
- Check out, edit, and return one file
- Versions and retained exports
- Invite catalogers and understand owner/editor/viewer roles
- Review notes and overall job status
- A generic recurring vendor-load example
- Complete, archive, and restore a job

The generic example uses one long-lived vendor job with two independent files:

1. Attach the current catalog extract or deletion file.
2. Check it out, run the required deletion edit, create a labeled retained
   export, load it to the external system, and mark that export loaded.
3. Attach the fresh vendor delivery as a second file in the same job.
4. Check out the fresh file, run the saved vendor task, review the result, and
   create the second retained export.
5. Return files for review or complete them independently while the job retains
   the shared people, notes, and activity context.

The guide explicitly distinguishes:

- a **job**, which coordinates the overall shared project;
- a **file**, which has its own checkout, current version, workflow state,
  approval context, and exports;
- a **retained export**, which records one exact file version prepared for an
  external load.

It also states that job status is advisory coordination for the overall project
and does not replace each file's independent state.

## Permissions and Existing Behavior

The redesign calls the existing service functions and retains current role
checks:

- owners and editors can update job status and add/resolve review notes;
- owners alone manage people and archive/restore the job;
- viewers can inspect files, notes, people, activity, and current status;
- file-level attachment, checkout, mutation, approval, version, and export
  controls continue to enforce their existing permissions.

Moving a control into a column, dialog, or tab must not broaden or narrow its
authorization. Existing errors remain displayed beside the action that caused
them, inside the corresponding panel or tab.

## Implementation Shape

Keep `marcedit_web/views/B_Jobs.py` as the thin page renderer. Extract only
small, single-purpose render functions needed to make the approved hierarchy
readable, such as help, handoff, notes, people, activity, and settings. Do not
introduce a new UI framework or general component abstraction.

Use existing Streamlit controls and project conventions:

- `st.dialog` for full in-page help;
- `st.columns` for Files and Next handoff;
- `st.tabs` for secondary content;
- existing `job_files` rendering helpers for attachment and file rows.

Resolve `docs/jobs.md` relative to the project/application source rather than
the process's current working directory, so tests and deployed startup paths do
not silently change the result.

## Testing and Verification

Tests must encode why the hierarchy matters, not merely count widget calls.
Coverage will verify that:

- help is discoverable on both the Jobs list and opened-job detail;
- the dialog renders the canonical guide or a visible fallback if it is
  unavailable;
- Files and Next handoff render before the secondary tabs;
- the tabs are named Review notes, People, Activity, and Settings;
- owner, editor, and viewer controls remain consistent with existing rules;
- archive/restore remains owner-only and is presented in Settings;
- the guide describes multiple independent files and the generic recurring
  vendor-load round trip;
- the Docker image includes the canonical Jobs guide.

Run focused Jobs-page and deployment tests during TDD, then the complete
workspace-mounted Docker suite. Completion requires zero failures and zero
skips, followed by code review and interactive verification of the Jobs list,
opened-job layout, dialog, and role-sensitive tabs.

## Success Criteria

- A cataloger can find help without leaving their current Jobs context.
- A cataloger can understand that one recurring job may contain multiple files
  processed and reviewed independently.
- Routine file and handoff work is visible near the top of an opened job.
- Secondary collaboration and administration features remain available without
  producing one long stacked page.
- No collaboration or persistence behavior changes unintentionally.
- Relevant and complete tests pass with zero skipped tests, and review is
  complete.
