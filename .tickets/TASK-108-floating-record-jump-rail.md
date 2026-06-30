# TASK-108 — Floating record editor jump rail

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User clarification 2026-06-30 — jump navigation should be a small
collapsible rail beside the editor work area, not the app sidebar
**Depends on:** TASK-107

## Title

Add a floating collapsible jump rail beside the structured record editor.

## Scope

- Replace sidebar jump links with an editor-local floating rail.
- Remove the main-page jump toolbar.
- Rail stays visible while scrolling the long record editor.
- Rail can collapse/expand using native HTML details/summary behavior.
- Preserve existing jump targets and anchors.
- Do not alter save, preview, validation, checkout/version, or snapshot logic.

## Success Criteria

1. Jump controls appear in a floating rail beside the work area.
2. The rail remains visible while scrolling.
3. The rail can collapse to reduce workspace obstruction.
4. Existing jump targets still navigate to field sections.
5. Focused tests and Docker suite pass before completion.
