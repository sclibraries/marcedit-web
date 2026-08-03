# TASK-190 Task 7 Implementation Report

Status: DONE_WITH_CONCERNS

Commit: `feat: persist safe migration review drafts` (this commit)

## Files changed

- `marcedit_web/lib/task_builder.py`
- `marcedit_web/lib/task_authoring.py`
- `marcedit_web/lib/native_tasks.py`
- `marcedit_web/lib/operation_runner.py`
- `marcedit_web/render/tasks.py`
- `tests/test_task_authoring.py`
- `tests/test_native_tasks.py`
- `tests/test_operation_runner.py`
- `tests/test_tasks_export.py`
- `tests/test_tasks_workspace_modes.py`

`operation_runner.py`, `test_operation_runner.py`, and `test_tasks_export.py`
are necessary additions to the plan's initial file list. The durable worker
reconstructs immutable queued `TaskSpec` values there, and the queue-boundary
tests contained the previous source-comment blocking contract.

## Implemented contract

- Added draft-only `migration-blocker` storage through the existing `# OP:`
  marker path. Rendering emits JSON metadata, inert explanatory comments, and
  a no-op `pass`; no external instruction or user-facing text becomes code.
- Added `migration_blockers(operations)` and the shared
  `assert_runnable_operations(operations)` gate with singular/plural bounded
  errors.
- Normalized blocker intent/reason whitespace and suggested operation kind
  without mutating input. Validation requires nonempty text, a lowercase
  64-character SHA-256 digest, a structured suggestion, a safe operation-kind
  token, mapping prefill parameters, JSON-safe finite literals, and no unknown
  blocker/suggestion keys.
- Allowed valid blockers through form validation and save/reopen. Saved drafts
  are labeled `Needs migration review` in the success message and form UI.
- Applied the same operation-level preflight to per-operation preview, queued
  submission before `TaskSpec`, durable-runner reconstruction before
  `TaskSpec`, and native runnable compilation.
- Removed runnable decisions based on historical `# TODO` source text. Only
  parsed structured operation markers trigger the migration gate; existing
  structured validation such as empty Find remains intact.
- Added adversarial coverage proving newline/code-like intent and reason text
  cannot escape comments or JSON markers.

## TDD evidence

Baseline before Task 7 changes:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_task_authoring.py tests/test_native_tasks.py tests/test_tasks_workspace_modes.py tests/test_operation_runner.py -q`

Exact result: `175 passed in 9.18s`; zero skipped and zero failed.

RED after adding Task 7 behavior tests:

Same command.

Exact result: `17 failed, 169 passed in 8.55s`; zero skipped. Failures were the
missing blocker API/validation/normalization, preview/native/queue/runner
gates, save allowance/label, and obsolete source-comment blocking behavior.

Focused GREEN after minimal implementation:

Same command.

Exact result: `186 passed in 8.69s`; zero skipped and zero failed.

## Final verification

Fresh consolidated immediate-caller, queue, storage, codegen, and native suite:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_task_authoring.py tests/test_native_tasks.py tests/test_tasks_workspace_modes.py tests/test_tasks_export.py tests/test_operation_runner.py tests/test_operation_submission.py tests/test_operation_queue_integration.py tests/test_task_db.py tests/test_codegen_safety.py tests/test_native_task_contract.py tests/test_native_task_storage.py -q`

Exact result: `345 passed in 15.74s`; zero skipped and zero failed.

Explicit native compiler contract freshness:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition -q`

Exact result: `1 passed in 0.17s`; zero skipped and zero failed.

`git diff --exit-code -- marcedit_web/schemas/native-task-compiler-contract-v1.json`
and `git diff --check` both exited 0 with no output. The native compiler
contract manifest did not change.

Full mounted-source suite:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest -q`

Exact result: `1 failed, 2356 passed, 5 skipped in 71.13s`. The sole failure
was the pre-existing generated operation-reference freshness drift at
`tests/test_operation_reference_registry.py::test_generated_operation_reference_is_fresh`:
the checked-in guide omits Task 5/6 predicate and operation updates already
present at start commit `4eeae07`. Task 7 does not change the palette entries
or guide generator that produced this diff, so the documentation repair is
outside this task's surgical scope.

Disclosed skips:

- 2 at `tests/test_docker_compose_config.py:88`: Docker CLI is required inside
  the test container.
- 2 at `tests/test_docker_compose_config.py:130`: Docker CLI is required inside
  the test container.
- 1 at `tests/test_task_authoring_corpus.py:105`: the private institutional
  corpus is not mounted; synthetic fixtures remain available.

## Concerns and disclosures

- No Task 7-focused or immediate-caller failure remains. The full suite is not
  globally green because of the disclosed pre-existing generated-reference
  drift; it must be repaired by the plan task that owns operation-reference
  regeneration.
- Historical comment-only unresolved text intentionally no longer blocks
  execution. This follows the marker-only requirement and avoids source-text
  pattern matching; only a validated `migration-blocker` marker carries the
  new fail-closed contract.
- Independent parent review remains required before TASK-190 can be marked
  Completed.
