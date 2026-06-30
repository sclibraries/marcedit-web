# TASK-102 — Record editor save, preview, and jump controls

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User request 2026-06-30 — avoid scrolling to save, optional preview
before save, and jump navigation
**Depends on:** TASK-101

## Title

Improve structured record editor controls for long MARC records.

## Scope

- Add top-of-editor save/cancel controls so saving does not require scrolling.
- Add save controls after each major editing section.
- Add a `Preview before saving` checkbox.
- When preview is enabled, a save click shows the changed record preview and
  requires confirmation before committing.
- Add jump links for common field groups so catalogers can move around long
  records.
- Keep validation, checkout/version checks, snapshots, and existing save path.

## Success Criteria

1. Save is available at the top of the structured editor.
2. Save is available after editing sections.
3. Preview-before-save shows the changed record and waits for confirmation.
4. Jump links are generated from the current record draft.
5. Focused tests and Docker suite pass before completion.
