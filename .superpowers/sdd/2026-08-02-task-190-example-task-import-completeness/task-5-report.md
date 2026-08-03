# TASK-190 Task 5 Implementation Report

Status: DONE

Commit: `feat: add structured field predicates` (this commit)

## Files changed

- `marcedit_web/lib/field_predicates.py`
- `marcedit_web/lib/transforms.py`
- `marcedit_web/lib/task_builder.py`
- `marcedit_web/lib/task_authoring.py`
- `marcedit_web/lib/external_task_parser.py`
- `marcedit_web/lib/external_task_migration.py`
- `marcedit_web/lib/ai_task_draft.py`
- `marcedit_web/render/task_authoring.py`
- `marcedit_web/render/task_operation_dialog.py`
- `marcedit_web/schemas/external-task-compatibility-v1.json`
- `tests/test_field_predicates.py`
- `tests/test_operations.py`
- `tests/test_task_authoring.py`
- `tests/test_external_task_migration.py`
- `tests/test_ai_task_draft.py`
- `tests/test_transforms.py`
- `tests/fixtures/external_task_migration/field-predicate-operations.tasksfile.txt`

The parser, operation dialog, AI validator, and transform tests are necessary
immediate callers beyond the brief's initial file list. They keep shape IDs,
guided controls, AI fail-closed validation, and the corrected cross-type COPY
contract synchronized. The native compiler contract manifest did not change.

## Implemented contract

- Added a leaf predicate engine importing only the standard library and pymarc.
  It accepts exactly `ind1`, `ind2`, `ind1_not`, `ind2_not`, and ordered
  `subfield_matches` entries containing exactly `code`, `mode`, `value`, and
  `ignore_case`.
- Rejects empty/malformed/unknown predicates, contradictory indicator choices,
  invalid subfield codes, empty match values, unsupported modes, invalid regex,
  and indicator/subfield predicates on control fields.
- Extended Copy Field and matched Delete with optional structural predicates.
  Filtered `856` to `857` copies preserve sources, indicators, subfields, and
  source-field order. Matched Delete removes only selected fields.
- The compiler emits the complete predicate through `data_lit()`. Malformed
  falsy values remain present and fail closed; they never become unfiltered
  operations. `repr(dict(params))` is not used.
- Added guided “Limit which fields are affected” indicator and subfield rows,
  including cataloger summaries such as “Copy 856 to 857 only when $3 contains
  JSTOR.”
- Added value-neutral `copy-v1` evidence and expanded `delete-v1` evidence in
  the incremental compatibility manifest. The private corpus remains untracked.

## External signature decisions

- `COPY 856 857 false $3JSTOR ... false` converts to a subfield-contains
  predicate. Any changed Boolean, extra filter value, malformed filter, or
  control-field filter remains an actionable blocker.
- Plain matched DELETE preserves the established any-subfield contains scope;
  it does not invent a `$a` restriction.
- Exact mnemonic `\6$a` converts to blank indicator 1, indicator 2 `6`, and
  `$a` existence. Exact regex-enabled `9\$a(...)` converts to indicators `9`
  and blank plus a `$a` regex predicate. Changed flags or malformed mnemonic
  shapes remain blockers.
- The corpus `COPY 001 035` signature is intentionally blocking. Independent
  runtime review proved pymarc discards control-field `data` when constructing
  data tag `035`, producing an empty field. Runtime, authoring, AI ingestion,
  and migration all reject control/data shape crossings; same-shape copies
  remain supported. This is a fail-closed correction to the broad design claim
  that every unfiltered COPY can convert.

## RED evidence

- Initial required suite: collection error because
  `marcedit_web.lib.field_predicates` did not exist.
- Mnemonic characterization: `6 failed, 118 passed`; existence/regex modes and
  the exact mnemonic adapters were absent.
- Guided controls: `1 failed`; the predicate controls did not exist.
- Regex escape regression: `1 failed`; case-folding changed `\S` into `\s`.
- Summary regression: `1 failed`; blank indicators and subfield existence were
  not described clearly.
- Review counterexamples: cross-type COPY and any-subfield DELETE produced
  `2 failed`; malformed falsy predicates produced `3 failed`; malformed AI
  predicate produced `1 failed`; end-to-end cross-type authoring/AI produced
  `2 failed`.

Every RED failed for the intended missing or unsafe behavior before its
production change.

## GREEN evidence

Final required suite:

`docker compose run --rm marcedit-web pytest tests/test_field_predicates.py tests/test_operations.py tests/test_task_authoring.py tests/test_external_task_migration.py tests/test_codegen_safety.py tests/test_native_task_contract.py -q`

Exact result: `323 passed in 6.42s`; 0 skipped, 0 failed.

Final expanded relevant suite:

`docker compose run --rm marcedit-web pytest tests/test_field_predicates.py tests/test_operations.py tests/test_task_authoring.py tests/test_external_task_migration.py tests/test_codegen_safety.py tests/test_native_task_contract.py tests/test_task_operation_dialog.py tests/test_external_task_parser.py tests/test_ai_task_draft.py tests/test_transforms.py tests/test_task_builder.py -q`

Exact result: `577 passed in 6.84s`; 0 skipped, 0 failed.

The real native compiler contract freshness test passed. No generated compiler
output changed, so `native-task-compiler-contract-v1.json` was not regenerated.
The external compatibility manifest changed intentionally for registered Task
5 adapter evidence and validated as JSON inside Docker.

## Review and concerns

- Independent review initially found one Critical and two Important issues:
  lossy cross-type COPY, falsy predicates failing open, and an invented `$a`
  scope for plain DELETE. Re-review then found the guided suggested operation
  could still execute cross-type COPY. All four paths received RED/GREEN
  regressions and were corrected.
- Final independent re-review reported no remaining Critical or Important
  findings.
- No pytest tests were skipped. One host-only `python -m json.tool` invocation
  failed because the host has no `python` executable; the same validation was
  rerun successfully in the project Docker image.
- AI drafting policy and supported operation set are unchanged. Validation now
  rejects only malformed Task 5 JSON predicates and proven-lossy cross-shape
  copies.

## Fix round 1 — exact evidence and fail-closed ordering

Commit: `fix: tighten field predicate migration evidence` (this commit)

### Parent-review findings fixed

- Restricted regex-mnemonic DELETE conversion to two exact full signatures:
  the reviewed local corpus signature and its sanitized `(ABC)` equivalence
  fixture. The accepted tag is exactly `035`, the mnemonic indicators/code are
  exactly `9\$a`, and the flags are exactly
  `(True, False, False, False, False)`. Parser classification and migration use
  one SHA-256 allowlist so the untracked institutional token is not committed.
- The external parentheses are grouping syntax, not literal MARC data. The
  allowlisted grouped token is translated to a case-sensitive structural
  `contains` predicate for the inner token; no external regex reaches Python.
  Changed values, indicators, codes, case, tags, flags, and `.*` all block with
  an actionable field-filter suggestion.
- Removed automatic conversion for every unfiltered COPY signature. There is
  no registered same-shape unfiltered equivalence fixture, so `650→651` and
  other unfiltered copies remain confirmation blockers. The registered
  `copy-v1` manifest row still represents only filtered `$codeVALUE` COPY with
  the exact false/false flags and empty surplus filter columns.
- Changed plain matched DELETE execution to filter `record.fields` in place.
  Matching fields are removed while every retained field remains at its exact
  original index relative to all interleaved fields.
- AI draft ingestion now passes predicate objects through the same
  `validate_field_predicate` leaf schema as authoring and runtime. Unknown keys
  and every other malformed structure are rejected in `DraftReview`.
- Replaced the invalid `001→035` Copy Field recommendation with a valid Build
  Field operation: `035` blank indicators, `$a` sourced from control field
  `001`, append policy, and skip when the source is missing. Other cross-type
  directions return a non-executable Choose Operation recommendation with a
  concrete manual source-selection step.

### RED evidence

- Importer remediation command: `4 failed, 113 deselected`. It reproduced the
  overbroad `9\$a.*` conversion, automatic unfiltered `650→651`, invalid
  `001→035` Copy recommendation, and non-actionable data-to-control COPY.
- AI/order command initially produced `1 failed, 1 passed`; AI accepted
  `{"unexpected": true}` while the first order fixture did not yet expose the
  move. After correcting the interleaving fixture, the order regression failed
  independently because the retained `655` moved across a `245`.
- Exact-signature near variants produced `3 failed, 2 passed`; changed
  indicator, subfield code, and tag still converted. Adding changed token
  `(ABD)` produced `1 failed, 3 passed`, proving the remaining generalized
  value family.

### GREEN evidence

Focused migration/parser/AI/transform suite before the final exact-value
allowlist: `264 passed in 1.09s`; 0 skipped, 0 failed.

Final required suite:

`docker compose run --rm marcedit-web pytest tests/test_field_predicates.py tests/test_operations.py tests/test_task_authoring.py tests/test_external_task_migration.py tests/test_codegen_safety.py tests/test_native_task_contract.py -q`

Exact result: `332 passed in 7.70s`; 0 skipped, 0 failed.

Final expanded relevant suite:

`docker compose run --rm marcedit-web pytest tests/test_field_predicates.py tests/test_operations.py tests/test_task_authoring.py tests/test_external_task_migration.py tests/test_codegen_safety.py tests/test_native_task_contract.py tests/test_task_operation_dialog.py tests/test_external_task_parser.py tests/test_ai_task_draft.py tests/test_transforms.py tests/test_task_builder.py -q`

Exact result: `588 passed in 7.57s`; 0 skipped, 0 failed.

The native compiler contract freshness guard still passes and its manifest
remains unchanged. The compatibility manifest also remains unchanged in this
fix round because its filtered COPY and exact mnemonic DELETE rows already
name only the registered automatic shapes; parser and adapter acceptance are
now tightened to those exact evidence boundaries.

### Review and remaining concerns

- Independent fix-round review first rejected the generalized parenthesized
  token family. After the exact shared digest allowlist and `(ABD)` regression,
  final re-review reported no remaining Critical or Important findings.
- No tests were skipped or silently omitted. No blocker remains for Task 5.
