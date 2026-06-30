# TASK-100 — Make MarcEditor default to record editor

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User report 2026-06-30 — MarcEditor still opens full-batch `.mrk`
after TASK-099
**Depends on:** TASK-099

## Title

Make the MarcEditor tab default to the cataloger-friendly one-record editor.

## Scope

- The MarcEditor tab should open on the one-record structured editor, not the
  full scrollable `.mrk` batch source editor.
- Keep the full-batch `.mrk` editor available as an explicit Advanced / Source
  mode for users who need batch/source editing.
- Preserve the existing over-cap behavior: large files use one-record editing
  and do not render the full-batch source editor.

## Success Criteria

1. A normal loaded file under the full-batch cap defaults to one-record editing.
2. The full-batch `.mrk` editor remains available by deliberate selection.
3. Files above the cap still use one-record editing.
4. Focused tests and Docker suite pass before completion.
