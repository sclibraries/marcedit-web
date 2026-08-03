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

## Fix round 1 — strict execution-boundary preflight

Commit: `fix: enforce migration preflight at sandbox boundary` (this commit)

### Review findings fixed

- Added dependency-light `marcedit_web/lib/task_preflight.py` as the single
  marker parser and runnable gate. It scans every present `# OP:` marker,
  rejects malformed JSON, malformed marker shapes, duplicate JSON keys, and
  non-finite JSON constants without relying on form-editable state.
- Moved direct sandbox enforcement before work-directory creation, task JSON
  serialization, or `Popen`. A `TaskSpec` containing a valid blocker plus
  executable mutation code now raises before a child exists.
- Applied the same strict body gate at queued submission, immutable worker
  reconstruction before `TaskSpec`, and rendered native compilation. Normal
  handwritten bodies without markers remain runnable.
- Tightened blocker validation: tuple values are not JSON-safe; every mapping
  key must be text; blocker and suggestion keys are closed allowlists;
  non-string/mixed keys return bounded errors rather than sorting/formatting
  exceptions; unknown keys are counted without echoing attacker-controlled
  text.
- Removed native compilation's rendered-source `# TODO:` substring check.
  Native structured operations remain the semantic allowlist, and legitimate
  Build Field text containing `# TODO:` now compiles as literal data.

`sandbox.py`, `task_preflight.py`, `tests/test_sandbox.py`, and the additional
sandbox-caller tests are necessary additions to Task 7's original file list.
The Critical direct-execution finding cannot be closed solely in the original
UI/native files because `run_tasks_subprocess` is the lowest public execution
boundary.

### RED evidence

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_task_authoring.py tests/test_native_tasks.py tests/test_tasks_workspace_modes.py tests/test_operation_runner.py tests/test_sandbox.py -q`

Exact result before production changes: `11 failed, 230 passed in 17.27s`;
zero skipped. The failures reproduced direct child launch for blocker code,
malformed-marker queue/worker bypass, tuple acceptance, mixed-key `TypeError`,
unbounded 10,000-character key echo, nested non-string key acceptance, and
native literal `# TODO:` rejection.

### GREEN evidence

Focused review suite, final run:

Same command.

Exact result: `241 passed in 18.78s`; zero skipped and zero failed.

Expanded direct-sandbox, caller, native, storage, and codegen suite:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_task_builder.py tests/test_task_authoring.py tests/test_native_tasks.py tests/test_native_task_contract.py tests/test_native_task_storage.py tests/test_task_db.py tests/test_tasks_workspace_modes.py tests/test_tasks_export.py tests/test_operation_runner.py tests/test_operation_submission.py tests/test_operation_queue_integration.py tests/test_sandbox.py tests/test_guided_replace_preview.py tests/test_guided_replace_validation.py tests/test_batch_replace.py tests/test_codegen_safety.py -q`

Exact result: `498 passed in 25.65s`; zero skipped and zero failed.

Explicit native compiler contract freshness after remediation:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition -q`

Exact result: `1 passed in 0.13s`; zero skipped and zero failed. The compiler
contract manifest has no diff, and `git diff --check` exited 0.

Fresh pre-commit focused plus codegen/native guard:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_task_authoring.py tests/test_native_tasks.py tests/test_tasks_workspace_modes.py tests/test_operation_runner.py tests/test_sandbox.py tests/test_codegen_safety.py tests/test_native_task_contract.py -q`

Exact result: `301 passed in 19.39s`; zero skipped and zero failed.

Full mounted-source suite:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest -q`

Exact result: `1 failed, 2366 passed, 5 skipped in 58.62s`. The sole failure
remains the pre-existing generated operation-reference freshness drift already
disclosed above; it is unchanged by this remediation.

Disclosed skips remain:

- 2 at `tests/test_docker_compose_config.py:88`: Docker CLI required inside
  the test container.
- 2 at `tests/test_docker_compose_config.py:130`: Docker CLI required inside
  the test container.
- 1 at `tests/test_task_authoring_corpus.py:105`: private institutional corpus
  unavailable.

### Remaining concern

- No Critical or Important Task 7 review finding remains. The unrelated
  generated operation-reference failure still prevents a globally green
  repository suite and remains owned by the operation-reference plan task.

## Fix round 2 — durable submission and token-aware markers

Commit: `fix: close migration submission and marker gaps` (this commit)

### Review findings fixed

- Added preflight to the direct durable submission payload boundary. Both
  `submit_job_task_run` and `submit_quick_load_task_run` now reject blockers,
  malformed markers, and unknown structured marker kinds before source access
  or copy, schema initialization, transaction creation, operation insertion,
  or queue side effects. Preflight failures retain the public
  `OperationError` contract.
- Replaced physical-line marker detection with Python `tokenize` COMMENT
  tokens. Standalone and inline markers are authoritative, while marker-like
  text inside ordinary or triple-quoted strings is ignored.
- Preserved ordinary explanatory comments such as `# OP: explain this task`
  as inert handwritten source. Once a comment claims a known marker shape, or
  supplies an object for a syntactically valid kind, malformed payloads fail
  closed. Tokenizer errors fail closed only when a structured marker candidate
  was already present, so unrelated malformed handwritten code remains outside
  the metadata gate.
- Added a dependency-light leaf allowlist containing every current palette
  kind plus `migration-blocker`. Unknown structured kinds such as
  `migration-blocker-v2` now fail closed at sandbox and durable submission
  boundaries. An explicit equality test keeps the leaf allowlist synchronized
  with `OPERATIONS_PALETTE` without introducing a heavy preflight import.
- Narrowed an existing raw-regex test monkeypatch to the user-supplied pattern.
  Python 3.9's tokenizer legitimately compiles its own grammar through the
  shared `re` module; the revised test continues to prove that the raw user
  expression is not compiled in the parent.

### RED evidence

Host diagnostic command before production changes:

`python3 -m pytest -q tests/test_task_authoring.py tests/test_sandbox.py tests/test_operation_submission.py`

The 11 new contract cases failed: four parser/allowlist cases, one direct
sandbox unknown-kind case, and six direct durable API cases. The same host run
also had 35 unrelated sandbox-process failures because the local Python 3.14
runner cannot apply the repository's `preexec_fn` resource limits. Container
verification below is authoritative.

### GREEN evidence

Focused parser, direct sandbox, and durable submission suite:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_task_authoring.py tests/test_sandbox.py tests/test_operation_submission.py -q`

Exact result: `178 passed in 10.97s`; zero skipped and zero failed.

Expanded task-builder, caller, native, storage, queue, sandbox, guided replace,
batch replace, and codegen suite:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_task_builder.py tests/test_task_authoring.py tests/test_native_tasks.py tests/test_native_task_contract.py tests/test_native_task_storage.py tests/test_task_db.py tests/test_tasks_workspace_modes.py tests/test_tasks_export.py tests/test_operation_runner.py tests/test_operation_submission.py tests/test_operation_queue_integration.py tests/test_sandbox.py tests/test_guided_replace_preview.py tests/test_guided_replace_validation.py tests/test_batch_replace.py tests/test_codegen_safety.py -q`

Exact result: `510 passed in 35.50s`; zero skipped and zero failed.

Explicit native compiler contract freshness:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition -q`

Exact result: `1 passed in 0.14s`; zero skipped and zero failed. The compiler
contract manifest has no diff, and `git diff --check` exited 0.

Full mounted-source suite:

`docker compose run --rm -v "$PWD:/app" marcedit-web pytest -q`

Exact result: `1 failed, 2378 passed, 5 skipped in 64.35s`. The sole failure
remains the pre-existing generated operation-reference freshness drift already
disclosed above. The five skips have the same Docker-CLI and unavailable
private-corpus reasons disclosed in the original report.

### Remaining concern

- No fix-round-2 Task 7 failure remains. The unrelated generated
  operation-reference drift still prevents a globally green repository suite
  and remains outside this surgical remediation.
