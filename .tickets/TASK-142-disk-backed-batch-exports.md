Title: Disk-backed batch exports

Scope:
- Replace in-session MARC export bytes with disk-backed export metadata for
  quick batch and Tasks outputs.
- Keep session state limited to paths, filenames, snapshot IDs, and ready flags.
- Preserve two-step prepare/download behavior so large files are read only when
  the user requests the download button.

Success Criteria:
- Quick batch export session state does not contain full MARC bytes.
- Quick batch export renders a Prepare button first, then a download button
  after the user requests it.
- Task run results prefer the sandbox output path over in-session bytes for
  download.
- Focused tests cover the memory-safe export path.

Verification:
- `docker compose exec marcedit-web pytest -ra tests/test_quick_batch_render.py tests/test_tasks_export.py`
  - 12 passed.
- `docker compose exec marcedit-web pytest -ra tests/test_quick_batch_render.py tests/test_tasks_export.py tests/test_quick_batch.py tests/test_ai_task_draft.py tests/test_tasks.py tests/test_snapshot_actions.py`
  - 71 passed.
- `git diff --check`
  - clean.

Status: Completed
