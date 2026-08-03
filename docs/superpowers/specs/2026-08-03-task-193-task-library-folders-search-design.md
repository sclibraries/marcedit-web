# TASK-193: Task-library folders and search design

## Objective

Replace the single mixed task list with a navigable library: personal and
shared folder trees on the left, and compact searchable task results on the
right. Organization must not change execution identity, ownership, or task
content.

## Data model

`task_folders` stores a stable ID, scope (`personal` or `shared`), personal
owner when applicable, parent ID, display name, revision, creator, and
timestamps. Tasks receive a nullable folder ID during schema transition and a
required valid folder assignment after migration. Root nodes are conceptual;
catalogers create at most three levels beneath My Tasks or Shared Tasks.

Folder names are unique case-insensitively within one parent and scope. A
personal folder can contain only its owner's tasks. A shared folder can contain
only shared tasks. Foreign keys and service-layer validation reject cross-scope
assignments. Moving a folder validates its complete descendant depth and
prevents cycles in the same transaction.

Task names do not become folder-relative. A personal task name is unique within
its owner's library, and a shared task name is unique across the shared
library. Sharing a task whose name conflicts with an existing shared task is
blocked until the cataloger renames one of them. Migration preflight reports
any historical shared-name conflict with both owners and task names and stops;
it never silently renames a task. Folder paths are presentation metadata, not
execution IDs.

## Authorization

Every signed-in cataloger can create, rename, move, and organize shared
folders, including moving shared tasks between them. These actions never
change task ownership or definition content. Every shared-folder mutation and
shared-task move records the acting identity, old parent/path, new parent/path,
and affected stable IDs in the audit log.

Personal folders are manageable only by their owner. Existing task editing and
deletion authorization remains unchanged. Search and counts always begin with
the existing visible-task authorization filter.

## Migration and visibility transitions

The additive migration creates one personal Unfiled folder per task owner and
one global Shared Tasks / Unfiled folder. Existing private tasks move to their
owner's Unfiled folder; existing shared tasks move to shared Unfiled. The
migration is transactional, idempotent, and does not rewrite definitions,
compiler snapshots, names, ownership, revisions, or timestamps except the new
folder association.

Sharing requires selecting a shared destination. Unsharing moves the task to
the owner's personal Unfiled folder unless another personal destination is
selected. New and imported tasks default to the currently selected compatible
folder, otherwise the applicable Unfiled folder.

Nonempty folders cannot be deleted. Catalogers must first move or delete their
tasks and child folders. Folder rename and move use optimistic revisions;
stale writes fail with a refresh message rather than overwriting another
cataloger's organization.

## User interface

The selected layout is a split library explorer. A persistent collapsible tree
shows My Tasks and Shared Tasks on the left. The right pane contains global
search, filters, folder breadcrumbs, and compact task results. Result rows show
name, description, owner, visibility, operation count, validation state,
updated time, and folder path. Folder and task moves use focused dialogs;
drag-and-drop is not required.

Search indexes cataloger-meaningful visible content: name, description, folder
path, owner, operation names, MARC tags, subfield codes, literal match and
replacement values, added values, and imported-source name. Generated Python,
fingerprints, and technical provenance are excluded. Filters cover
personal/shared, owner, operation kind, MARC tag, validation state, and recent
updates.

Search may derive a normalized document from the canonical native definition
and parsed legacy operations, cached by task revision. It must not require a
production SQLite extension. A task that cannot be structurally parsed remains
searchable by safe metadata without exposing raw executable source.

## Failure handling and testing

- Test personal/shared authorization, including private-result isolation.
- Test additive migration and repeat migration from realistic old schemas.
- Test rename, move, nonempty deletion, cycles, depth overflow, case-folded
  duplicates, stale revisions, and transactional rollback.
- Test every indexed content type and filter combination against visible and
  inaccessible tasks.
- Browser-test folder creation, navigation, search, sharing, unsharing, moving,
  imports, and editor return paths with a sufficiently large task library.
- Verify the older application tolerates the additive schema for rollback.

## Non-goals

- Duplicate task display names within the current identity model.
- More than three cataloger-created folder levels.
- Drag-and-drop as the only organization mechanism.
- Changing task ownership through folder actions.
- Searching generated Python or private task content.
