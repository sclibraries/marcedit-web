Title: Export and rollback after batch operations

Scope:
- After quick batch apply, offer a distinct updated MARC export filename without
  overwriting or renaming the source upload.
- Record a durable before/after snapshot for quick batch operations when the
  user/job context supports it.
- Make task-run export filenames visibly distinct from the source upload.
- Tell users where durable rollback/download history is available without
  redesigning the Tasks page layout.

Success Criteria:
- Quick batch apply stores a post-operation export payload with a filename that
  differs from the source filename.
- Quick batch apply creates a job snapshot when signed in and attached to a job.
- Task-run downloads use an operation-specific filename suffix.
- Users see clear in-page messaging about download and Job snapshots.

Status: Completed

Verification:
- 2026-07-09: `docker compose exec marcedit-web pytest -ra
  tests/test_quick_batch_render.py tests/test_tasks_export.py
  tests/test_quick_batch.py tests/test_ai_task_draft.py tests/test_tasks.py
  tests/test_snapshot_actions.py` passed (68 passed).
- 2026-07-09: `git diff --check` passed.
