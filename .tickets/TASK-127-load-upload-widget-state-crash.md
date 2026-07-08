# TASK-127 — Load from Home crashes on widget-owned current_job_id

**Status:** Completed
**Priority:** Tier 1 — Production crash in primary cataloger flow
**Depends on:** TASK-120, TASK-126

## Title

Guard the `current_job_id` write in `session.load_persisted_upload` so Load
works from Home's Job Workspace.

## Problem

Clicking **Load** in Home's "Files in this job" table raises
`StreamlitAPIException: st.session_state.current_job_id cannot be modified
after the widget with key current_job_id is instantiated.`

Root cause (traced 2026-07-08): `load_persisted_upload`
(`marcedit_web/lib/session.py:427`, introduced in fb9e0b8 / TASK-120)
assigns `st.session_state["current_job_id"]` unconditionally. On Home the
Job selectbox is created with `key="current_job_id"`, making the key
widget-owned for that script run; Streamlit forbids any later assignment —
even of the identical value. The Jobs page has no such widget, so the same
function works there. Not a storage/missing-file issue: the missing-file
branch returns a friendly error before the crashing line.

Why tests missed it: Home page tests enforce the widget-write rule but
monkeypatch `load_persisted_upload`; session tests run the real function
against a plain dict that doesn't enforce the rule.

## Scope

- In `load_persisted_upload`, skip the `current_job_id` assignment when the
  session value already equals the upload's `job_id` (always true on Home,
  where the table lists only the selected job's files).
- Preserve the existing behavior of updating `current_job_id` when loading
  an upload from a different job (Jobs page flow, key not widget-owned).
- Regression test in `tests/test_session_restore.py` using a session-state
  stand-in that raises on writes to widget-owned keys, mirroring real
  Streamlit.

## Success Criteria

1. A failing-first test reproduces the crash: `load_persisted_upload` with
   `current_job_id` widget-owned and equal to the upload's job succeeds.
2. A companion test pins the preserved behavior: with a non-widget-owned
   differing `current_job_id`, the value is updated to the upload's job.
3. Focused suites pass: `tests/test_session_restore.py`,
   `tests/test_home_page_jobs.py`, `tests/test_app_pages.py`.
4. Docker suite passes (same command as TASK-126).

## Outcome

- Guarded the `current_job_id` assignment in `load_persisted_upload`
  (`marcedit_web/lib/session.py`): write only when the value differs from
  the session's current job. Comment documents the widget-ownership rule.
- Added `_WidgetOwnedState` stand-in and two tests in
  `tests/test_session_restore.py`: the widget-owned regression (failed
  first with the exact production error, RuntimeError on the write) and
  the Jobs-page job-switch behavior pin.
- Verification:
  - RED: `python3 -m pytest tests/test_session_restore.py -q -k "widget_owned or switches_job"`
    → 1 failed (the regression, pre-fix), 1 passed.
  - GREEN local: `python3 -m pytest tests/test_session_restore.py tests/test_home_page_jobs.py tests/test_app_pages.py tests/test_jobs_page.py tests/test_jobs.py -q`
    → 68 passed.
  - GREEN Docker (Python 3.9 / Streamlit 1.50, the crashing environment):
    same five files → 68 passed.
- Code review: ready to merge, no Critical/Important findings.
