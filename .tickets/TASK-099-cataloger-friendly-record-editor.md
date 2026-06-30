# TASK-099 — Cataloger-friendly one-record MARC editor

**Status:** In-Progress
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User decision 2026-06-30 — raw `.mrk` is too hard for cataloger
editing
**Depends on:** TASK-091, TASK-095

## Title

Replace the default single-record raw `.mrk` editing workflow with a
cataloger-friendly one-record structured editor.

## Scope

- Default to one selected record at a time, matching the existing View/Edit
  record navigation surfaces.
- Render editable field rows for the current record:
  - control fields show tag + data;
  - variable fields show tag, two indicators, and repeatable subfield
    code/value rows.
- Allow field/subfield add, delete, and simple reordering for the current
  record.
- Keep the raw `.mrk` editor as an Advanced / Source mode for power users and
  emergency edits, not the default.
- Continue using the existing checkout/lock/version checks from TASK-095.
- Continue using existing validation, snapshots, and `RecordStore.replace`
  save behavior.
- Keep full-file MarcEditor available as advanced batch/source editing.

## Success Criteria

1. A cataloger can edit a normal variable field without typing `.mrk`
   syntax.
2. A cataloger can edit a control field without seeing escaped `.mrk`
   backslashes as the main UI.
3. The editor works one record at a time and preserves existing navigation.
4. Raw `.mrk` source mode remains available.
5. Checkout/version protections still gate save for shared jobs.
6. Focused tests and Docker suite pass before completion.
