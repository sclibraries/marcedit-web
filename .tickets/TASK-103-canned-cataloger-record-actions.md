# TASK-103 — Canned cataloger record actions

**Status:** Todo
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User request 2026-06-30 — routine record changes should not require
building a custom task each time
**Depends on:** TASK-099, TASK-102

## Title

Add reusable, cataloger-friendly canned actions for common record changes.

## Scope

- Add a “Canned changes” area to the one-record structured editor.
- Start with Leader-focused actions:
  - expose editable Leader positions with labels and allowed values;
  - protect/generated positions such as record length, base address, indicator
    count, subfield code count, directory lengths, and undefined bytes.
- Add an initial set of ebook-oriented normalization actions:
  - set 008 byte 23 to `o`;
  - add or normalize 336/337/338 with `$b`;
  - add or normalize `655 \7 $a Electronic books. $2 local`.
- Actions must preview the changed record before applying.
- Actions must save through the existing validation, checkout/version,
  snapshot, and `RecordStore.replace` path.
- Avoid exposing Python/task code to catalogers for these canned operations.

## Success Criteria

1. Catalogers can apply common Leader changes through labeled controls, not
   raw positional editing.
2. Catalogers can run initial ebook normalization actions without creating a
   custom task.
3. Generated/protected Leader positions are not manually editable through the
   canned action UI.
4. Every canned action shows a changed-record preview before applying.
5. Existing record checkout/version protection still gates saves.
6. Focused tests and Docker suite pass before completion.
