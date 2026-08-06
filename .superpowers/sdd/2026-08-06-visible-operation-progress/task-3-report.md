# Task 3 report

Status: DONE_WITH_CONCERNS (Quick batch and Find and replace activity integration implemented).

## Changes

- Replaced the duplicate `_quick_batch_progress` renderer with the shared
  activity helper for Quick batch preview/apply.
- Passed `ActivityHandle.progress_callback` unchanged to
  `quick_batch.build_preview` and `quick_batch.apply_preview`; the helper
  retains first/250/final cadence and unavailable-progress behavior.
- Added phase-only activity panels for Find and replace preview/apply, whose
  `batch_replace` engine request/result interfaces remain unchanged.
- Added operation IDs `quick-batch-preview`, `quick-batch-apply`,
  `quick-find-replace-preview`, and `quick-find-replace-apply`, including
  rerun completion summaries and completion/failure ordering before reruns.
- Added lifecycle, callback-boundary, phase, request-identity, and rerun-order
  coverage with local activity recordings.

## Tests

`PYTHONPATH=. pytest -q tests/test_quick_batch_render.py tests/test_quick_batch.py tests/test_batch_replace.py tests/test_task_quick_field_changes.py tests/test_quick_field_changes_render.py`

Result: **115 passed**, 0 skipped.

`python3 -m compileall -q marcedit_web/render/tasks.py` and `git diff --check`
also passed.

## Commit

- `b77cac2 feat: show quick batch activity progress`

## Concerns

- The first sandboxed commit attempt could not create the worktree index lock
  because `.git` is read-only in the default sandbox; the commit succeeded
  after the required escalation.
- Older `tests/test_quick_replace_snapshot.py` fakes do not patch the shared
  activity context and therefore fail when run in the broader legacy suite;
  the required Task 3/Task 2 command is green. Updating those unrelated test
  fakes is deferred to the parent integration pass.
