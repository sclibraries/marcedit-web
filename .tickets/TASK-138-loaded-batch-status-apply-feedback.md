Title: Loaded batch status and quick batch apply feedback

Scope:
- Add a clear loaded-batch status signal near the top of the Tasks view so
  catalogers can see which MARC file is active before running tasks or quick
  batch operations.
- Improve quick batch apply feedback so applying a large batch shows progress
  and does not leave competing/duplicate Apply buttons visible.
- Keep the change limited to UI/status behavior; do not change quick batch MARC
  mutation semantics.

Success Criteria:
- Tasks shows the active filename, record count, and malformed/skipped count
  when a batch is loaded.
- Quick batch preview/apply remains preview-first.
- Applying a quick batch operation shows a spinner/progress message and clears
  other stale quick-operation previews.
- Tests cover the loaded-batch status helper and quick batch apply feedback.

Status: Completed

Verification:
- 2026-07-09: `docker compose exec marcedit-web pytest -ra
  tests/test_loaded_batch_status.py tests/test_quick_batch_render.py
  tests/test_app_pages.py tests/test_ai_task_draft.py` passed (34 passed).
- 2026-07-09: `git diff --check` passed.
