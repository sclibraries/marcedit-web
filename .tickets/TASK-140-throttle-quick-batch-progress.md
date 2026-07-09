Title: Throttle quick batch progress updates

Scope:
- Fix slow quick batch preview/apply caused by updating Streamlit progress
  widgets once per record on large batches.
- Keep record-level progress callbacks in the core library, but throttle UI
  rendering so large batches update periodically and at completion.
- Do not change MARC mutation semantics.

Success Criteria:
- The Tasks UI progress callback updates Streamlit at a bounded frequency for
  large batches.
- Progress still reports first and final record counts.
- Focused quick batch tests pass.

Status: Completed

Verification:
- 2026-07-09: `docker compose exec marcedit-web pytest -ra
  tests/test_quick_batch_render.py tests/test_quick_batch.py
  tests/test_loaded_batch_status.py` passed (27 passed).
- 2026-07-09: `git diff --check` passed.
