# Task 8 Report: Per-Record Safe Fix Action

Ticket: `.tickets/TASK-148-folio-rule-profiles.md`

Status: Completed

## Changes

- Added `validate._find_single_folio_fix_rule()` to map a selected FOLIO issue code back to exactly one fixable structured rule for the current record.
- Extended `open_record_modal()` with optional `fix_label` and `on_fix` parameters.
- Added an in-modal "Apply FOLIO safe fix" button before the existing edit action when Validate opens a fixable FOLIO issue.
- Wired the callback to `folio_profiles.apply_record_fix()`, `store.replace()`, and `issues_cache` invalidation.
- Added the required helper test in `tests/test_validate_folio_profiles.py`.

## TDD Evidence

Red:

```bash
docker compose run --rm marcedit-web pytest tests/test_validate_folio_profiles.py::test_find_single_folio_fix_rule_returns_matching_rule -q
```

Result: failed as expected with `AttributeError: module 'marcedit_web.render.validate' has no attribute '_find_single_folio_fix_rule'`.

Green:

```bash
docker compose run --rm marcedit-web pytest tests/test_validate_folio_profiles.py::test_find_single_folio_fix_rule_returns_matching_rule -q
```

Result: `1 passed in 0.55s`.

Focused verification:

```bash
docker compose run --rm marcedit-web pytest tests/test_validate_folio_profiles.py tests/test_view_render.py -q
```

Result: `12 passed in 0.62s`.

## Self-Review

- Scope stayed limited to Task 8 behavior; no batch preview UI was added.
- Fix application remains structured through `folio_profiles.apply_record_fix()` and does not execute arbitrary Python.
- Validate only computes the per-record fix rule after a specific selected FOLIO issue is opened.
- Existing validation and preview batch streaming behavior was not changed.
- Full record lists were not added to Streamlit session state.

## Concerns

- The brief requested Docker focused tests; the documented service name was `app`, but this project compose file exposes `marcedit-web`. I used `marcedit-web`.
