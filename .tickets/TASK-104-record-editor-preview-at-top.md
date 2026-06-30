# TASK-104 — Show record save preview at top

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User report 2026-06-30 — preview confirmation appears below the
long editor, requiring scrolling to confirm
**Depends on:** TASK-102

## Title

Render preview-before-save confirmation at the top of the structured editor.

## Scope

- When `Preview before saving` is enabled and Save is clicked, show the changed
  record preview directly under the top action bar.
- Keep Confirm save and Keep editing controls next to that top preview.
- Do not require scrolling to the bottom of the record to confirm save.
- Preserve section save buttons, jump links, validation, checkout/version
  protection, snapshots, and existing save path.

## Success Criteria

1. Preview-before-save confirmation appears near the top controls.
2. Confirm save remains gated by the existing validation/save path.
3. Keep editing dismisses the pending preview without saving.
4. Focused tests and Docker suite pass before completion.
