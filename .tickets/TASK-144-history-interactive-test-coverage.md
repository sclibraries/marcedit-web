Title: History page interactive test-coverage gaps

Scope:
- Add tests pinning History-page behaviors that TASK-143 shipped with
  runtime verification but no automated coverage:
  - `_offer_diff` / `history_open_diff` lifecycle: opening a second
    snapshot's diff replaces the first (one-open-diff memory cap),
    Hide diff clears the key.
  - `history.render()` branch for a loaded batch with no backing
    `current_job_id` (info message, no timeline, no crash).
  - Quick find/replace apply with `current_job_id` unset / anonymous
    user: snapshot skipped, `job-snapshot-created` audit not emitted,
    apply still succeeds.

Success Criteria:
- Each behavior above has a focused test whose docstring states why
  the behavior matters (memory cap; graceful degradation; fail-open
  apply).
- Tests follow the existing fake-streamlit patterns in
  tests/test_history_render.py / tests/test_quick_replace_snapshot.py.

Status: Todo
