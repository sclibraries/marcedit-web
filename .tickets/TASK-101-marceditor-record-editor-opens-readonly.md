# TASK-101 — Open MarcEditor record editor directly

**Status:** Completed
**Priority:** Tier 4 — Cataloger editing UX
**Source:** User report 2026-06-30 — record mode shows a box that cannot be
edited
**Depends on:** TASK-100

## Title

Open the structured record editor directly in MarcEditor record mode.

## Scope

- In the MarcEditor tab's Record editor mode, show editable structured fields
  immediately for the selected record.
- Do not present the read-only record preview as the primary box users click
  into.
- Keep preview/source information available only as secondary context.
- Preserve View page behavior unless explicitly needed.

## Success Criteria

1. MarcEditor Record editor mode opens editable widgets without an extra
   “Edit this record” click.
2. The read-only record display is no longer the primary interaction target.
3. Focused tests and Docker suite pass before completion.
