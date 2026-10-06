Title: Fix missing download helper in saved-task run results

Status: In-Progress

Workspace: existing clean `.worktrees/task-253-mrk-upload`, baseline de040fc.

Scope:
- Locate the production-version task result renderer reported in the traceback.
- Restore its historical-file download helper with the smallest compatible fix.
- Add regression coverage and review the change.

Success Criteria:
- Reproduce the reported NameError in a regression test before fixing it.
- Completed task results offer their output download without a NameError.
- Relevant tests pass and code review completes; broader validation limitations are recorded.

Plan (TASK-254): locate the matching checkout, reproduce the result-rendering failure, fix the missing dependency, run validation, and review the diff.

Completion — 2026-10-06:
- Restored the missing import of History's existing download helper in the production-version task renderer. Main uses a different runner and was not modified.
- Added a Streamlit AppTest that reproduced the exact NameError before the fix and now exercises Prepare, rerun, and download-button rendering successfully.
- Focused validation: `PYTHONPATH="$PWD" python3 -m pytest tests/test_task_result_download.py tests/test_tasks_export.py tests/test_tasks_workspace_modes.py -q`: 143 passed, zero skipped, 64 deprecation warnings.
- Full validation with the same PYTHONPATH: 2,793 passed, 8 failed, 1 skipped, 4,394 warnings. All eight failures also reproduce on an untouched archive of baseline de040fc (8 failed). They concern existing operations UI expectations and sandbox process/memory restrictions.
- Skipped: tests/test_task_authoring_corpus.py:106 because the institutional task corpus is unavailable in this checkout.
- Initial runs without PYTHONPATH had subprocess package-import failures (focused: 5 failed/138 passed; full: 79 failed/2,722 passed/1 skipped); corrected environment results above supersede those runs.
- Independent read-only code review found no issues or import cycle; reviewer independently passed the new test. Simplification review retained the minimal one-line production fix. `git diff --check` passed.
- Validation used local Python 3.14 / Streamlit 1.57; production Python 3.9 / Streamlit 1.50 was not exercised. Browser download transport was not tested.
- Changes are local and uncommitted in the existing production worktree. No deployment performed.

Baseline-reproduced full-suite failures:
- tests/test_operation_runner.py::test_heartbeat_ownership_failure_propagates_and_cleans_attempt
- tests/test_operations_render.py::test_large_result_is_never_materialized_for_streamlit_download
- tests/test_operations_render.py::test_terminal_actions_call_job_and_quick_load_services
- tests/test_operations_render.py::test_action_errors_are_shown_without_mutating_row
- tests/test_operations_render.py::test_job_viewer_can_download_but_never_sees_mutation_controls
- tests/test_sandbox.py::test_cancellation_terminates_sandbox_process_group
- tests/test_sandbox.py::test_long_running_task_times_out
- tests/test_sandbox.py::test_memory_bomb_killed_or_caught

Integration — 2026-10-06:
- User requested merge and push. Apply only TASK-254 to current origin/main (b227046), excluding the earlier MRK-upload release commits.
- Revalidate the integrated tree and push main after verification; production deployment is outside this request.
