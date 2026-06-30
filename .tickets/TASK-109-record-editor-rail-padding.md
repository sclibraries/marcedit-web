# TASK-109 — Record editor rail padding

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User request 2026-06-30 — floating jump rail can cover controls
such as Delete
**Depends on:** TASK-108

## Title

Reserve workspace padding for the floating record jump rail.

## Scope

- Add desktop-only right-side padding to the structured record editor area
  while the floating jump rail is present.
- Keep mobile/narrow viewport layout unchanged.
- Do not alter jump targets, save, preview, validation, checkout/version, or
  snapshot logic.

## Success Criteria

1. Main editor controls are not covered by the floating jump rail on desktop.
2. Narrow screens do not lose excessive workspace.
3. Focused tests and Docker suite pass before completion.
