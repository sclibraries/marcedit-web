# TASK-190 Task 4 Implementation Report

Status: DONE

Commit: `feat: migrate guided subfield instructions` (this commit)

## Files changed

- `marcedit_web/lib/external_task_migration.py`
- `marcedit_web/lib/external_task_parser.py`
- `marcedit_web/lib/marcedit_import.py`
- `marcedit_web/schemas/external-task-compatibility-v1.json`
- `tests/test_external_task_migration.py`
- `tests/test_guided_replace.py`
- `tests/test_guided_replace_validation.py`
- `tests/test_marcedit_import.py`
- `tests/fixtures/external_task_migration/subfield-operations.tasksfile.txt`

`marcedit_web/lib/task_authoring.py` did not require a production change. The
new adapters emit the existing operation contracts unchanged, and focused
tests prove every automatic output passes its existing authoring validation.

## Implemented contract

- Replaced `subfield-edit-v1` with `subfield-edit-v2` and added
  `subfield-remove-v1`, including value-neutral shape IDs, incremental
  manifest rows, and sanitized fixture evidence that must convert through the
  registered adapter.
- Converted literal `SUBFIELD_EDIT ... 0|0` to guided matched-text replacement,
  exact `^b` to guided prepend, exact `^e` to guided append, and empty Find
  with `101|0` to `empty-find-subfield-policy` / `add_if_missing`.
- Converted `SUBFIELD_REMOVE ... 107|0` to exact, case-sensitive,
  whitespace-preserving `delete-subfield-if-value`.
- Kept unsupported caret forms, pipe-move syntax, option combinations,
  malformed targets, malformed columns, and other near misses blocking. Every
  blocker carries plain-language intent and reason, a recommended operation,
  only safely prefilled parameters, and a concrete cataloger action.
- Extended the legacy tasksfile emitter only as required by its immediate
  caller contract so guided prepend/append, explicit empty-find policy, and
  exact subfield removal render deterministic operations rather than crashing
  or falling through as unknown syntax.

## Characterization decision

The local `.task` archives contain the exact corpus signature
`SUBFIELD_REMOVE 035 z (OCoLC) 107|0`. No installed MarcEdit binary/package or
local corpus evidence contradicted the approved design. The characterization
therefore uses the existing deterministic exact-value delete operation and
proves that repeated matching `035 $z` values are removed while:

- a whitespace near-match remains;
- a nonmatching `$z` remains;
- every other subfield remains;
- both `035` fields and their order remain.

The adapter sets `trim=False`; trimming would broaden exact matching without
external evidence.

## RED evidence

Required focused command after adding Task 4 tests:

`docker compose run --rm marcedit-web pytest tests/test_external_task_migration.py tests/test_guided_replace.py tests/test_guided_replace_validation.py -q`

Exact result: `25 failed, 161 passed in 1.76s`; 0 skipped. Failures covered
missing prepend/append and empty-find conversion, missing remove dispatch,
non-actionable near misses, cataloging effects, authoring validation, and
manifest evidence.

Legacy immediate-caller RED after aligning its intended tests:

`docker compose run --rm marcedit-web pytest tests/test_marcedit_import.py -q`

Exact result: `2 failed, 18 passed in 0.76s`; 0 skipped. Empty-find conversion
crashed the guided-only emitter, and `SUBFIELD_REMOVE` was still unknown.

Independent-review regressions:

`docker compose run --rm marcedit-web pytest tests/test_external_task_migration.py -q -k 'parser_approved_empty_surplus or subfield_remove_107 or subfield_remove_preserves' tests/test_marcedit_import.py::test_subfield_remove_maps_to_exact_value_deletion`

Exact result: `4 failed, 1 passed, 98 deselected in 0.14s`; 0 skipped. Both
adapters crashed on parser-approved trailing empty columns, and exact removal
incorrectly trimmed whitespace.

Pipe-move safe-prefill regression:

`docker compose run --rm marcedit-web pytest tests/test_external_task_migration.py::test_pipe_move_blocker_explains_why_it_cannot_convert -q`

Exact result: `1 failed in 0.30s`; 0 skipped. The blocker initially copied the
opaque pipe expression into an otherwise executable guided parameter set.

## GREEN evidence

Final required focused suite:

`docker compose run --rm marcedit-web pytest tests/test_external_task_migration.py tests/test_guided_replace.py tests/test_guided_replace_validation.py -q`

Exact result: `189 passed in 1.84s`; 0 skipped, 0 failed.

Final relevant expanded suite:

`docker compose run --rm marcedit-web pytest tests/test_external_task_parser.py tests/test_external_task_migration.py tests/test_guided_replace.py tests/test_guided_replace_validation.py tests/test_marcedit_import.py tests/test_task_authoring.py tests/test_task_builder.py tests/test_transforms.py tests/test_codegen_safety.py tests/test_native_task_contract.py -q`

Exact result: `497 passed in 8.09s`; 0 skipped, 0 failed.

## Review and decisions

- Official MarcEdit documentation confirms exact `^b` prepend, exact `^e`
  append, and a distinct pipe syntax for moving data. Only the two exact caret
  forms convert; combined caret/text forms, `^c`, and pipe moves remain inert
  suggestions.
- Prepend/append use `match_mode=none`, empty Find, and all selected values, so
  they mutate existing target subfields only and never create a missing source
  subfield.
- Empty Find converts automatically only for option `101|0`; the generated
  policy adds one value only to fields missing that code.
- Parser-approved surplus empty columns are sliced away at the adapter's
  canonical arity. Nonempty surplus columns remain parser errors and structured
  blockers.
- Independent review identified and verified fixes for trailing-empty-column
  crashes and unintended whitespace trimming. A follow-up re-review found no
  remaining Critical or Important issues.

## Concerns and disclosures

- No Task 4 blocker remains.
- No AI drafting behavior changed.
- The legacy importer files are additional to the brief's initial file list
  because that production caller directly consumed `adapt_subfield_edit` and
  otherwise crashed on the newly proven operation kind; it also needed the
  new removal verb to avoid classifying a proven adapter as unknown.
- The private corpus remains untracked. Only synthetic fixture values are
  committed.

## Fix round 1 — empty-find workspace persistence contract

Commit: `test: align empty-find import persistence`

### Review finding fixed

- Replaced the stale workspace integration test that expected empty-Find
  `SUBFIELD_EDIT ... 101|0` to be rejected.
- The integration boundary now proves one task is persisted, its stored body
  reopens as exactly one `empty-find-subfield-policy` operation with
  `policy=add_if_missing`, and the durable import result reports success.
- The test also proves the persisted body contains neither a
  `migration-blocker` nor a `# TODO` unresolved marker.
- No production behavior changed in this fix round.

### RED evidence

Original stale integration test:

`docker compose run --rm marcedit-web pytest tests/test_tasks_workspace_modes.py::test_empty_find_import_is_not_persisted -q`

Exact result: `1 failed in 3.04s`; 0 skipped. The failure showed the current
successful import result (`success`) contradicting the obsolete expected
result (`rejected`).

### GREEN evidence

Exact updated integration test:

`docker compose run --rm marcedit-web pytest tests/test_tasks_workspace_modes.py::test_empty_find_101_import_persists_add_if_missing_operation -q`

Exact result: `1 passed in 1.61s`; 0 skipped, 0 failed.

Relevant workspace modes suite:

`docker compose run --rm marcedit-web pytest tests/test_tasks_workspace_modes.py -q`

Exact result: `46 passed in 1.88s`; 0 skipped, 0 failed.

Task 4 focused suite:

`docker compose run --rm marcedit-web pytest tests/test_external_task_migration.py tests/test_guided_replace.py tests/test_guided_replace_validation.py -q`

Exact result: `189 passed in 0.92s`; 0 skipped, 0 failed.

Task 4 expanded suite:

`docker compose run --rm marcedit-web pytest tests/test_external_task_parser.py tests/test_external_task_migration.py tests/test_guided_replace.py tests/test_guided_replace_validation.py tests/test_marcedit_import.py tests/test_task_authoring.py tests/test_task_builder.py tests/test_transforms.py tests/test_codegen_safety.py tests/test_native_task_contract.py -q`

Exact result: `497 passed in 5.66s`; 0 skipped, 0 failed.

### Concerns

- None. This fix round changes only the stale integration contract and its
  implementation report.
