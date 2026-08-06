# Task 4 report

Status: COMPLETE (saved-task runs now use the shared activity lifecycle).

## Changes

- Replaced `_execute_synchronous_run`'s local `st.status` lifecycle with the
  shared `saved-task-run` activity helper, including Preparing and Sandbox
  execution phases with the loaded record total.
- Preserved task parsing/spec construction, synchronous sandbox invocation,
  timeout/nonzero labels, output parsing, snapshot/audit evidence, cleanup,
  and retained result payloads.
- Routed sandbox timeout, nonzero exit, pre-output exceptions, and successful
  runs through the helper's collapsed failure/completion states.
- Added renderer integration coverage using real `TaskSpec`/`SandboxResult`
  values for success, timeout, and nonzero-exit outcomes.

## Tests

`PYTHONPATH=. pytest -q tests/test_tasks_export.py tests/test_synchronous_task_runner.py`

Result: **29 passed**, 5 warnings (existing `datetime.utcnow()` deprecation).

Additional helper regression run:

`PYTHONPATH=. pytest -q tests/test_tasks_export.py tests/test_synchronous_task_runner.py tests/test_operation_activity.py`

Result: **36 passed**, 5 warnings.

`python3 -m compileall -q marcedit_web/render/tasks.py` and `git diff --check`
also passed.

## Commit

Pending commit after parent review.

## Concerns

- No worker, queue, database, file, sandbox, cancellation, timeout, or MARC
  semantic changes were made.
