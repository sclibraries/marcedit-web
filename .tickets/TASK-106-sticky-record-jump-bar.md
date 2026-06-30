# TASK-106 — Sticky record editor jump bar

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User request 2026-06-30 — jump controls should travel with the
cataloger while editing long records
**Depends on:** TASK-102

## Title

Keep structured record editor jump links visible while scrolling.

## Scope

- Replace the plain markdown jump line with a sticky jump bar.
- Keep the jump bar compact so it does not cover record fields.
- Preserve existing jump targets and anchors.
- Do not alter save, preview, validation, checkout/version, or snapshot logic.

## Success Criteria

1. Jump controls remain visible while scrolling through a long record.
2. Existing jump targets still navigate to the same field sections.
3. Focused tests and Docker suite pass before completion.
