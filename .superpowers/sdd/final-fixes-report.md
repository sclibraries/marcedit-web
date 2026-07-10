## TASK-148 Final FOLIO Fixes - 2026-07-10

Scope:
- Fixed FOLIO snapshot provenance to pass both pre-mutation and post-mutation staged store paths.
- Added structured preview rule fingerprints for stale-preview detection.
- Added per-rule affected record tracking for batch preview rows.

Red evidence:
- `docker compose run --rm marcedit-web pytest tests/test_folio_profile_fixes.py tests/test_validate_folio_profiles.py -q`
- Result before implementation: 7 failed, 16 passed.
- Expected failures covered missing `affected_records_by_rule`, stale same-key rule definition changes, and missing `before_path` in `_record_folio_snapshot`.

Green evidence:
- `docker compose run --rm marcedit-web pytest tests/test_folio_profile_fixes.py tests/test_validate_folio_profiles.py -q`
- Result after implementation: 23 passed in 0.47s.

Requested verification:
- `docker compose run --rm marcedit-web pytest tests/test_folio_profile_fixes.py tests/test_validate_folio_profiles.py tests/test_validate_styling.py tests/test_validate_view_button.py tests/test_view_render.py tests/test_record_store.py -q`
- Result: 92 passed in 0.61s.
