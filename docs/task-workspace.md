# Tasks workspace guide

The Tasks page is organized around four activities. The selected activity is
kept in the URL, so browser Back and Forward can restore the cataloger's
working view. Search text and filter values may appear in the URL; task
definitions, imported instructions, MARC records, OAuth values, and unsaved
form fields never do.

## Choose an activity

- **Run** is where reusable work is applied. **Saved tasks** runs a task from
  the library and **Quick changes** applies a one-time controlled operation
  without creating a saved task. The Run selector changes between those two
  modes; only the selected mode is shown.
- **Library** is the catalog of visible tasks. Browse Personal or Shared
  folders, search task metadata and operation content, apply filters, and use
  the task or folder actions. Editing a task from Library opens it in Create;
  its stable task ID and ownership are retained.
- **Create** is the structured task editor. Use it for a new task or for a
  task opened from Library. Saving changes the task; moving between activities
  does not discard an unsaved draft.
- **Import** accepts a MarcEdit `.tasksfile` (`.txt`) or `.task` archive. The
  import result is a reviewable draft. Adopt a converted result into Create,
  where it can be checked and edited before saving. Imported source text is
  kept in the current session, not in the URL.

## Saved tasks and Quick changes

Saved tasks are reusable definitions in the task library. They can be filtered,
organized, shared, and run again. Quick changes are intentionally one-off:
choose the operation and its values, apply it to the current records, and use
the result without changing the saved-task library. Choose Saved tasks when a
workflow should be repeatable; choose Quick changes for a temporary edit.

## Library search, filters, and history

Type search text or change a Library filter to stage a value. The results still
use the last applied URL state until **Apply filters** is selected. Typing and
intermediate filter changes do not add browser-history entries. **Apply
filters** writes the complete staged set once; **Clear filters** writes one
reset state. Each action therefore creates one Back/Forward entry.

Selecting a folder, task, scope, or dialog is also a single navigation entry.
Back and Forward restore the selected view, folder, applied filters, and
authorized task or dialog target. A refresh restores that URL state as well.
If a linked task or folder is no longer visible to the signed-in cataloger,
the target is cleared and the safe Library view is shown instead of opening it.

## Personal and Shared folders

Library folders are separated into **Personal** and **Shared** locations.
Personal folders organize tasks owned by the signed-in cataloger. Shared
folders organize shared tasks visible to collaborators. Moving or editing a
task changes its organization or content, not its owner or visibility.

Use the prominent **Create new folder** action to choose a written-out
Personal or Shared location, enter a name, and select a compatible parent.
When a folder is selected, choose **Create subfolder here** to open the same
dialog with that folder preselected as the parent; the parent can be changed
before saving. The conceptual **Unfiled** root in each location is a stable
anchor and cannot be renamed, moved, or deleted. Folder depth is limited by
the workspace contract, so an invalid parent or depth is rejected without a
partial change.

## Drafts, navigation, and discard

Create and Import drafts are retained in the current browser session even
when their activity is not being rendered. Back, Forward, refreshes that only
change the Tasks query, and switching among Run, Library, Create, and Import
do not put the draft in the URL or discard it. A new browser session does not
recover an old unsaved draft.

Use **Discard draft** in Create when the working copy is no longer wanted.
Discard draft is explicit: it clears the unsaved Create copy, while ordinary
navigation only changes the visible activity. For Import, keep the review or
adopt it into Create; leaving Import alone does not publish or save it.

## Dialogs and unavailable targets

Every task-library and operation dialog has a visible escape action. Use
**Cancel** for Create, Rename, Move, Share, Unshare, Import, Delete, and other
editing dialogs. Use **Close** for read-only references, previews, and stale or
informational states. Cancel clears only that dialog's working copy and URL
target; it does not change the task, folder, saved definition, surrounding
Library view, or Create draft.

Browser Back closes an open dialog while retaining its recoverable session
draft. Forward can reopen it only when the URL target is still authorized and
visible. A stale or inaccessible dialog target is not resurrected: the page
shows the bounded message **“That dialog target is no longer available.
Close this message.”** with a Close action. Invalid or inaccessible linked
tasks and folders similarly fall back to the safe Library view with the target
cleared. No navigation or dialog failure changes stored task or folder data.
