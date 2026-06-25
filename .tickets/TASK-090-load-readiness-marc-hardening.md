# TASK-090 — Explicit load-readiness MARC hardening checks

**Status:** Completed
**Priority:** Tier 3 — catalog loading safety
**Source:** Cataloger feedback: make FOLIO/EDS CC load prerequisites explicit

## Title

Make FOLIO / EDS CC load-readiness checks explicit in validation/preflight.

## Scope

- Surface explicit checks for records being loaded to FOLIO or EDS CC:
  MARC validity, 006 present and valid, 007 present and valid, 008 byte 23 is
  `o` and not `s`, and 336/337/338 are present, correctly formed, and include
  `$b`.
- Fit into the existing validation/preflight flow rather than adding a separate
  unrelated workflow.
- Decide whether these checks are warnings or blocking errors before
  implementation.

## Success Criteria

1. Validation output names each load-readiness issue explicitly.
2. Missing/invalid 006, 007, 008 byte 23, and 336/337/338 `$b` cases are covered
   by focused tests.
3. The checks are available for both FOLIO and EDS CC load review.
4. Existing validation and upload behavior does not regress.

## Implementation Plan

Ticket link: `.tickets/TASK-090-load-readiness-marc-hardening.md`

1. Add focused tests in `tests/test_load_readiness.py` for the shared
   FOLIO / EDS CC warning profile.
2. Create `marcedit_web/lib/load_readiness.py` with a pure
   `validate_records(records)` function returning warning `Issue` objects.
3. Integrate the new pass into `marcedit_web/render/validate.py` after
   preflight and rule validation so the warnings appear in the existing issue
   table.
4. Extend issue-to-tag highlighting so load-readiness rows open the relevant
   record field.
5. Run focused tests, then commit TASK-090 as a rollback checkpoint.
