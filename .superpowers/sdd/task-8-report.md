# Task 8 Report — Immutable labeled exports and manual load audit

Ticket: [TASK-151](../../.tickets/TASK-151-job-file-work-items-implementation.md)

## Status

Implemented and verified. TASK-151 remains In-Progress because later plan tasks
are outside this Task 8 slice.

## Implemented

- Added transactional `create_export`, `get_export`, `list_exports`, and
  `mark_export_loaded` services.
- Export creation rechecks owner/editor access, archive state, active checkout,
  and the exact opened current version under `BEGIN IMMEDIATE`.
- Export bytes stream to unique retained per-file `exports/` paths and are
  checked against the immutable version's byte and record counts before the row
  is inserted.
- Exact approved current versions create `ready` exports and set the file to
  `exported`; unapproved versions create visibly distinct `draft` exports.
- Later version adoption continues to supersede only draft/ready exports;
  loaded audit evidence and all retained bytes remain untouched.
- Manual load confirmation requires owner/editor access and a destination, does
  not require checkout, records external id/note/actor/timestamp, and does not
  complete the file.
- History & review now renders the file's export form/list, explicit lifecycle
  labels, two-step downloads from each retained export path, and manual load
  controls. Completion remains a separate existing workflow action.

## TDD Evidence

- Service RED: `tests/test_job_file_workflow.py` failed because the four export
  service APIs did not exist.
- Service GREEN: `11 passed`.
- UI RED: two renderer tests failed because `render_file_exports` did not exist.
- UI GREEN: both renderer tests and the History integration test passed.
- Review-fix RED: the first focused run produced three intended failures for
  missing post-validation checkout recheck, destructive UUID collision, and
  over-broad Create export controls (`3 failed, 3 passed`). A separate cleanup
  ownership regression then failed because a missing source could delete a
  colliding retained path (`1 failed`).
- Review-fix GREEN: post-validation authority, collision retry, partial-copy
  cleanup, pre-persist rollback, persisted-then-raised reconciliation,
  holder-only UI, and collision cleanup-ownership regressions all passed
  (`7 passed` plus the final ownership regression `1 passed`).

## Verification

- Focused Task 8 suite:
  `PYTHONPATH=. pytest -q tests/test_job_files.py tests/test_tasks_export.py tests/test_job_file_workflow.py tests/test_history_render.py`
  — `53 passed`.
- Full zero-skip suite in the declared Python 3.9 container with the complete
  worktree mounted read-only:
  `docker compose run --rm -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/task-151-job-file-work-items:/app:ro marcedit-web pytest -q`
  — `1199 passed in 17.57s`.
- `git diff --check` passed.

## Review Fix Verification

- Focused Task 8/export/history/adoption suite in the Python 3.9 container:
  `pytest -q tests/test_job_files.py tests/test_tasks_export.py tests/test_job_file_workflow.py tests/test_history_render.py tests/test_job_file_mutations.py`
  — `81 passed in 2.37s`.
- Fresh full zero-skip suite after all review fixes:
  `docker compose run --rm -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/task-151-job-file-work-items:/app:ro marcedit-web pytest -q`
  — `1205 passed in 16.81s`.
- Export creation now rechecks role, archive state, exact current version, and
  the unexpired holder checkout after copy/MARC validation and immediately
  before insertion/status/activity changes.
- Export copy uses exclusive `xb` target creation with collision retry. Cleanup
  removes only a path exclusively created by the attempt and reconciles any
  surviving path against SQLite before deletion.
- Create export controls now require a non-archived owner/editor who actively
  holds the file checkout with the exact current opened-version token. Other
  users retain list/download visibility.

## Concerns

- Host Python lacked `streamlit_ace`, so a direct host full-suite collection was
  invalid. The standard container image also omits repository-only benchmark,
  deploy, and documentation files, producing two failures and nine skips. The
  final complete-worktree container run resolved both environment limitations
  and had zero skips.
- Task 8 review findings were reproduced with regression tests and resolved.
- Pre-existing Task 7 Minor findings remain intentionally out of scope.
- My Task 8 commands did **not** create the untracked `uv.lock`; no command in
  either implementation pass invoked `uv`. The file remains untouched and is
  not staged.
