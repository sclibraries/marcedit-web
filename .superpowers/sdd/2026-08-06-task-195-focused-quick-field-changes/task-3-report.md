# TASK-195 Task 3 Report — Structured sandbox adapter envelope

Status: DONE

## Delivered

- Extended `TaskSpec` with trailing `adapter` and `adapter_payload` fields,
  preserving all existing positional construction, and added trailing
  `SandboxResult.adapter_totals`.
- Added parent-side mutually exclusive body/adapter validation, the literal
  `quick-field-change` allowlist, canonical sorted compact JSON payload
  serialization, and JSON/character/byte bounds. The child performs all
  Quick operation-shape validation without compiling raw regular expressions
  in the Streamlit process.
- Added child-side literal adapter preparer dispatch, envelope and payload
  revalidation, one-time adapter preparation before record iteration, bounded
  changed/unchanged/skipped and affected-field totals, and capped reason-code
  counts.
- Preserved legacy task-body execution, output cardinality, and captured and
  partner totals. Adapter failures restore the original record before writing
  the output record.
- Added parent generic-envelope and forged-child rejection tests for mixed
  envelopes, unknown adapters, non-JSON payloads, malformed operations,
  oversized payloads, and a parent `re.compile` spy for raw-regex adapters.
  Added mutation, aggregate, original-record, and no-op regression tests.

## Verification

Focused adapter/no-op command:

```text
PYTHONPATH=. pytest -q tests/test_sandbox.py -k 'adapter or noop_task_round_trips'
15 passed, 48 deselected
```

Task 3 adjacent validation command:

```text
PYTHONPATH=. pytest -q tests/test_quick_field_changes.py tests/test_quick_field_selector.py tests/test_preflight.py
79 passed
```

Broader sandbox/preflight command:

```text
PYTHONPATH=. pytest -q tests/test_sandbox.py tests/test_preflight.py
81 passed, 3 failed
```

The three failures are the established local macOS sandbox process-group and
memory-limit failures (`test_cancellation_terminates_sandbox_process_group`,
`test_long_running_task_times_out`, and `test_memory_bomb_killed_or_caught`);
the adapter/no-op tests and all preflight tests pass. The broader related run
also retained the known heartbeat ownership failure, for four pre-existing
environmental failures total.

`python3 -m py_compile marcedit_web/lib/sandbox.py tests/test_sandbox.py` and
`git diff --check` pass.

## Commit

Initial implementation: `9764ad6 feat: add structured sandbox adapters`

## Review Fix Round 1

- Removed parent-side Quick request parsing and validation; the parent now
  owns only generic envelope and canonical payload bounds, with operation
  preparation and validation performed in the child.
- Lazy-loaded `quick_field_changes` only when the child selects the literal
  allowlisted adapter, preserving the legacy body-only dependency boundary.
- Strengthened rollback coverage with a valid mutating adapter followed by an
  invalid raw-regex adapter; the output remains the original record.

Verification after the review fixes:

```text
PYTHONPATH=. pytest -q tests/test_sandbox.py -k 'adapter or noop_task_round_trips'
15 passed, 48 deselected

PYTHONPATH=. pytest -q tests/test_sandbox.py tests/test_preflight.py
81 passed, 3 failed
```

The same three local macOS process-group/resource-limit failures remain.

Review-fix commits:

- `3028248 fix: keep quick adapter validation in sandbox child`
- `d79640f refactor: lazily dispatch sandbox adapters`

## Concerns

None for the structured adapter implementation. Docker/Linux remains the
authoritative environment for the existing process-group and resource-limit
sandbox tests.
