# TASK-059 — Human-readable task authoring

**Status:** Completed

## Title

Create a text-based task authoring path that converts regular cataloging
notes into reviewable Tasks form-builder operations.

## Scope

- Add a way for a cataloger to paste plain, human-readable task notes.
- Translate supported note lines into existing task-builder operations.
- Show a review/edit step before saving the generated task.
- Fail loud on unsupported or ambiguous lines instead of guessing.
- Keep the existing form-builder and sandbox execution model.

## Success Criteria

1. A Routledge EBA-style note can be pasted and converted into a draft
   ordered operation list for the Tasks page.
2. Supported operations are deterministic and covered by tests.
3. Unsupported lines are reported with clear messages and are not silently
   dropped.
4. The generated task can be saved, reopened in form view, and run through
   the existing sandbox path.
5. Full test verification passes before this ticket is marked completed.
