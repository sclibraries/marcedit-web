# TASK-095 — Record checkout and read-only edit UI

**Status:** Completed
**Priority:** Tier 4 — Collaboration
**Parent:** TASK-086
**Depends on:** TASK-093, TASK-094
**Design ADR:** `docs/adr-collaboration-locking.md`

## Title

Gate inline record and fixed-field editing behind record checkout locks.

## Scope

- Add checkout/release controls around inline record edit surfaces.
- Disable save controls for non-holders and viewers.
- Re-check lock ownership and version token immediately before saving.
- Show lock holder and expiry near edit controls.

## Success Criteria

1. One editor can check out a record; another user sees read-only/locked state.
2. The holder can save; non-holders and viewers cannot.
3. If the lock expires or the version changed, save fails loud.
4. Focused tests and Docker suite pass before completion.

## Outcome

- Added record checkout/release controls to inline record editing.
- Disabled inline and fixed-field save actions for viewers and non-holders.
- Re-checks lock ownership and job version immediately before record or
  fixed-field saves.
- Ignores expired lock rows in the UI so records can be checked out again.
- Final verification: `docker compose run --rm marcedit-web python -m pytest -q`
  passed with `871 passed, 5 skipped`.
