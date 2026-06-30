# TASK-105 — Record save preview modal

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User request 2026-06-30 — preview should be a modal over the editor
instead of replacing the input display
**Depends on:** TASK-104

## Title

Show preview-before-save in a modal dialog.

## Scope

- Replace the inline pending preview panel with a `st.dialog` modal.
- Keep the structured editor visible behind the modal.
- Modal shows the changed record preview, validation feedback, `Confirm save`,
  and `Keep editing`.
- Confirm save continues through the existing validation, checkout/version,
  snapshot, and `RecordStore.replace` path.
- Dismissing the modal returns to the editor without saving.

## Success Criteria

1. Clicking Save with preview enabled opens a modal instead of hiding the editor.
2. Confirm save in the modal uses the existing save path.
3. Keep editing closes the preview state without saving.
4. Focused tests and Docker suite pass before completion.
