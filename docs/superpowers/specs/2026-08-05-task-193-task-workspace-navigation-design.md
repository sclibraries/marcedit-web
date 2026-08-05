# TASK-193: Task workspace navigation and dialog usability

## Objective

Reorganize the Tasks workspace into four clearly named activities, preserve
the cataloger's exact working context through browser navigation, make folder
creation discoverable, and guarantee an explicit way out of every modal.

This design extends the existing
[TASK-193 task-library design](2026-08-03-task-193-task-library-folders-search-design.md).
It reorganizes existing task workflows without changing task execution,
authorization, migration, or storage semantics.

## Workflow navigation

Replace the current horizontal radio choices with a stateful, tab-style
segmented navigation bar:

- **Run**
- **Library**
- **Create**
- **Import**

Run has a second tab-style selector with **Saved tasks** and **Quick changes**.
Only the selected workflow is rendered. Library, Create, and Import no longer
share one long Build & import surface.

Streamlit 1.50 remains the production contract. Its native `st.tabs` does not
expose selected-tab state or an `on_change` callback, so it cannot update the
URL or implement browser Back and Forward. The navigation therefore uses
`st.segmented_control` presented as a tab strip. This keeps the existing
Python 3.9 and Streamlit dependency boundary while providing controlled state,
conditional rendering, and URL synchronization.

The workflow responsibilities are:

- **Run / Saved tasks:** select and synchronously run reusable saved tasks.
- **Run / Quick changes:** apply controlled one-time operations.
- **Library:** browse, search, filter, organize, share, and open tasks for edit.
- **Create:** author a new structured task or edit one opened from Library.
- **Import:** upload an external task, review migration results, and adopt a
  converted draft into Create.

Opening an existing task from Library selects Create in edit mode. Adopting an
import selects Create with the converted task as an unsaved draft. Navigating
away does not discard either draft. An explicit **Discard draft** action is the
routine way to clear an unsaved Create draft.

## Library actions

Replace the small `+ Personal folder` and `+ Shared folder` controls with one
prominent primary action labeled **Create new folder**. Its dialog requires:

- a folder name;
- a written-out Personal or Shared location; and
- a compatible parent folder.

When a folder is selected, **Create subfolder here** opens the same dialog with
that folder selected as the parent. The cataloger may change the compatible
parent before saving.

Color is supplementary rather than semantic. The create action combines the
primary color with a `+` icon and explicit text. Rename, Move, Share, Unshare,
and Delete retain written labels. Destructive actions use explicit destructive
wording and confirmation.

## URL and browser-history contract

The Tasks URL is the canonical navigation state. The following query
parameters are supported:

| Parameter | Meaning |
| --- | --- |
| `view` | `run`, `library`, `create`, or `import` |
| `mode` | `saved` or `quick` when `view=run` |
| `scope` | `personal` or `shared` in Library |
| `folder` | Stable visible folder ID |
| `q` | Library search text |
| `visibility` | `all`, `private`, or `shared` |
| `owner` | Library owner filter |
| `tag` | MARC tag filter |
| `subfield` | Subfield-code filter |
| `operation` | Structured operation-kind filter |
| `validation` | `all`, `valid`, `legacy`, or `invalid` |
| `updated` | `any`, `7`, or `30` |
| `task` | Stable visible task ID when editing |
| `dialog` | The currently open task-library dialog kind |
| `dialog_task` | Stable visible task ID targeted by a task dialog |
| `dialog_folder` | Stable visible folder ID targeted by a folder dialog |

On initial load and browser Back or Forward, valid URL state restores the
selected view, Run mode, Library scope, folder, filters, task editor, dialog,
and authorized dialog target. A synchronization guard distinguishes an
external URL change from the application's own write so Streamlit reruns
cannot create a loop.

Streamlit 1.50 calls its page-change path for query-only browser history
changes, even when the pathname and page script remain the same. Create and
Import working copies therefore live in explicitly managed, non-widget session
keys. They are not allowed to depend only on widget keys, which Streamlit may
remove when their owning workflow is not rendered. Unsaved Create and Import
draft survival across Back and Forward is a required failing regression test
before the navigation implementation begins.

History entries are divided by interaction cost:

- Primary view, Run mode, scope, folder, task, and dialog changes write the URL
  immediately and create one browser-history entry. That write also commits
  any staged Library filters atomically so navigation never discards filter
  work or creates a second entry.
- Library search text and the visibility, owner, tag, subfield, operation,
  validation, and updated filters are staged in a form. **Apply filters**
  writes all staged values to the URL once. **Clear filters** writes one reset
  state. Typing and intermediate filter selection never write the URL.
- Until Apply or structural navigation, staged values remain visible with a
  **Filters not applied** indication while results continue to reflect the
  applied URL state.
- A committed filter URL restores both the applied search and its widget
  values on Back, Forward, refresh, or a shared link.

This avoids a separate history entry for every intermediate search string or
filter selection while preserving the complete applied Library view.

Tasks owns only the parameters enumerated in the table above. A canonical
write starts from the current query mapping, replaces or removes only those
Tasks-owned keys, and writes the merged mapping atomically. It never clears the
complete query mapping. In particular, it preserves `job_file`, which is read
and written by `lib/session.py`, and `start`, which is read and written by
`views/00_Home.py`. Other non-Tasks keys are also preserved so a future
application surface cannot be silently erased by Tasks navigation.

Unknown values within Tasks-owned keys, malformed IDs, stale IDs, and
inaccessible task or folder IDs are removed from the Tasks-owned parameter set
and fall back to the nearest valid view. They never bypass authorization or
raise an unbounded exception.

Search text and cataloger-facing filter values may appear in browser history.
Task definitions, imported instruction bodies, MARC record data, OAuth data,
and unsaved field values never enter the URL.

URL navigation state and unsaved working state have distinct ownership:

- URL state survives refresh, sharing, and browser history traversal.
- Unsaved Create and Import working copies remain in Streamlit session state.
- Browser Back restores the view that owns the working copy without
  serializing that copy into the URL.
- A new browser session does not recover an unsaved draft from an old session.

## Modal contract

Every modal must have a visible footer escape action even when its target is
missing, stale, inaccessible, or otherwise invalid:

- **Cancel** for Create, Rename, Move, Share, Unshare, Import, Delete, and other
  action dialogs.
- **Close** for read-only references, previews, and informational dialogs.

The primary action is visually distinct and appears opposite Cancel or Close.
Cancel clears only the modal working copy and dialog URL state. It does not
change a task, folder, saved definition, selected Library view, or surrounding
Create draft. Operation-editor Cancel discards only that operation's dialog
working copy.

Library dialogs remain non-dismissible outside this explicit path so a click
outside the modal cannot silently discard input. Browser Back clears the
`dialog`, `dialog_task`, and `dialog_folder` parameters and closes the modal
while retaining its recoverable session working copy. Forward may reopen it if
its authorized target remains available.

The URL is authoritative for whether a dialog is open; a retained working copy
is never sufficient to reopen one. Dialog input is copied into an explicitly
managed, non-widget session value keyed by dialog kind and target. When an
external history change has no valid dialog parameters, synchronization clears
the open-dialog state before rendering but retains that value. Forward
rehydrates dialog widgets from it only after validating the URL target. An
explicit Cancel or successful primary action closes the dialog and deletes its
retained working copy.

One shared library-dialog close routine clears the dialog kind, target IDs,
dialog error, and dialog-only widget state before rerunning. Error branches
render their Close action before returning.

## Component boundaries and data flow

A small deterministic navigation module owns parsing, validation,
canonicalization, and serialization of Tasks query parameters. It does not
import Streamlit and does not read or modify task definitions, MARC records,
or database rows. The renderer supplies the visible task and folder IDs used
for authorization-aware validation.

`render/tasks.py` owns the tab-style segmented controls, transfers widget
changes into the navigation model, writes canonical query parameters, and
renders exactly one workflow. Existing Run, Quick, Library, Editor, and Import
renderers remain authoritative for their business behavior.

The synchronization flow is:

1. Read the complete query mapping and parse only Tasks-owned keys into a
   bounded navigation value.
2. Validate enum values and numeric syntax deterministically.
3. Resolve visible task and folder IDs through existing authorization-aware
   library APIs.
4. Apply external URL state to navigation and applied-filter session keys
   without changing explicitly managed Create, Import, or dialog working-copy
   keys.
5. Render the selected workflow.
6. On a structural navigation interaction or Apply/Clear filters, merge the
   new canonical Tasks state with all non-Tasks query parameters and perform
   one atomic URL write.

Folder creation, moves, task saves, imports, and execution continue through
their existing service APIs. Navigation never becomes a second persistence
path.

## Failure handling

- An invalid `view` falls back to Run / Saved tasks.
- An invalid Run `mode` falls back to Saved tasks.
- An invalid or inaccessible folder returns to its valid scope root.
- An invalid or inaccessible task returns to Library without opening an
  editor.
- An invalid dialog target shows a bounded error and an explicit Close action.
- Invalid filters revert individually; one bad value does not discard the
  other valid URL state.
- URL/session synchronization detects its own canonical write and does not
  rerun indefinitely.
- Intermediate search typing and filter changes do not create browser-history
  entries before Apply filters.
- A query write preserves `job_file`, `start`, and every other non-Tasks key.
- No navigation failure changes database state or discards an unsaved draft.

## Verification

Automated tests must cover:

- parsing and canonical serialization of every supported parameter;
- valid round trips and independent rejection of every invalid value;
- authorization boundaries for task and folder IDs;
- primary and secondary tab selection;
- restoration of every Library filter and selected folder;
- a RED-to-GREEN regression proving unsaved Create and Import working copies
  survive query-only Back and Forward page re-initialization;
- preservation and explicit discard of Create and Import working copies when
  their widgets are not rendered;
- one history write for Apply filters and no writes for intermediate search or
  filter changes;
- merged query writes that preserve `job_file`, `start`, and unknown non-Tasks
  parameters;
- navigation from Library edit and Import adoption into Create;
- explicit Cancel or Close in every library-dialog mode;
- closure from validation-error, stale-target, inaccessible-target, and
  no-destination branches;
- browser Back closing an open dialog despite a retained working copy, and
  Forward reopening it only from valid URL dialog state;
- Personal, Shared, root, and selected-parent folder creation;
- the existing task execution, quick-change, importer, authorization, search,
  task-library, and operation-dialog suites; and
- Python 3.9 and Streamlit 1.50 Docker execution.

Authenticated browser verification must exercise Back and Forward across all
four primary views, both Run modes, folder selection, filter changes, task
editing, import review, and an open dialog. It must also verify that the URL
contains no task-definition, imported-instruction, MARC-record, or unsaved form
content.

## Non-goals

- Upgrading Streamlit to obtain newer stateful native tabs.
- Persisting unsaved drafts across browser sessions or service restarts.
- Changing task execution, compiler, migration, storage, or authorization
  semantics.
- Adding durable Operations or worker behavior.
- Changing systemd, sudoers, OAuth, proxy, or other ITS-managed configuration.
- Encoding task definitions or MARC data in URLs.
