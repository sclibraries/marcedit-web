# TASK-107 — Record editor jump links in sidebar

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User request 2026-06-30 — sticky jump bar does not stay visible;
use the sidebar instead
**Depends on:** TASK-106

## Title

Move structured record editor jump links into the sidebar.

## Scope

- Render record jump links in `st.sidebar` while the structured record editor
  is open.
- Keep a lightweight in-page jump line near the top as a fallback.
- Remove the custom sticky jump-bar CSS from TASK-106.
- Preserve existing jump target generation and anchors.
- Do not alter save, preview, validation, checkout/version, or snapshot logic.

## Success Criteria

1. Jump links are visible in the sidebar while editing long records.
2. In-page jump links still appear near the top of the editor.
3. Existing field anchors continue to work.
4. Focused tests and Docker suite pass before completion.
