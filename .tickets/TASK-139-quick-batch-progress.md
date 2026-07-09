Title: Quick batch record progress feedback

Scope:
- Show record-level progress while building quick batch previews.
- Show record-level progress while applying a quick batch preview, including
  stale-preview validation before the final store swap.
- Keep progress reporting optional in the core quick batch library so tests and
  non-UI callers can run without Streamlit dependencies.

Success Criteria:
- Quick batch preview reports processed/total counts through a callback.
- Quick batch apply reports processed/total counts through a callback.
- The Tasks UI displays progress bars and status text for preview/apply.
- Existing preview-first and stale-preview safety behavior remains intact.

Status: Completed

Verification:
- 2026-07-09: `docker compose exec marcedit-web pytest -ra
  tests/test_quick_batch.py tests/test_quick_batch_render.py
  tests/test_loaded_batch_status.py tests/test_ai_task_draft.py` passed
  (51 passed).
- 2026-07-09: `git diff --check` passed.
