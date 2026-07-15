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

## Verification

- Focused Task 8 suite:
  `PYTHONPATH=. pytest -q tests/test_job_files.py tests/test_tasks_export.py tests/test_job_file_workflow.py tests/test_history_render.py`
  — `53 passed`.
- Full zero-skip suite in the declared Python 3.9 container with the complete
  worktree mounted read-only:
  `docker compose run --rm -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/task-151-job-file-work-items:/app:ro marcedit-web pytest -q`
  — `1199 passed in 17.57s`.
- `git diff --check` passed.

## Concerns

- Host Python lacked `streamlit_ace`, so a direct host full-suite collection was
  invalid. The standard container image also omits repository-only benchmark,
  deploy, and documentation files, producing two failures and nine skips. The
  final complete-worktree container run resolved both environment limitations
  and had zero skips.
- The controller requested immediate handoff before the nested independent
  reviewer returned. That reviewer was stopped; the controller is performing
  the formal Task 8 review.
- Pre-existing Task 7 Minor findings remain intentionally out of scope.
