Title: Make long-running operation progress visible in-page

Design: [Visible operation progress](../docs/superpowers/specs/2026-08-06-visible-operation-progress-design.md)
Plan: [Visible operation progress implementation](../docs/superpowers/plans/2026-08-06-visible-operation-progress.md)

Scope:
- Replace spinner-only feedback for long Quick operations with a visible
  in-page status panel.
- Reuse existing progress callbacks and `st.status` conventions for Quick
  Find and replace, focused Quick field changes, and specialized Quick batch
  operations.
- Preserve operation semantics, sandbox boundaries, and existing completion
  and error handling.
- Retain only a bounded serializable completion summary in Streamlit session
  state so Quick-path reruns can show the final status; do not add database or
  file persistence.

Success Criteria:
- A cataloger sees a clear in-page activity message while a long operation is
  preparing, previewing, applying, or finalizing.
- Where record progress is available, the panel shows processed and total
  records with a progress bar.
- Completion, cancellation, and failure leave a readable final status.
- Existing operation results, stale-preview rules, and downloads are unchanged.
- Tests cover status lifecycle and progress updates without requiring a
  browser.

Status: Completed

Implementation and verification checkpoint (2026-08-07):
- Shared activity helper, focused Quick operations, Quick batch/Find and
  replace, and saved-task runs are implemented and independently reviewed.
- Focused regression suite: 159 passed, 5 existing datetime deprecation
  warnings.
- Authoritative Docker suite: 2773 passed, 5 skipped. Skips are the two
  Docker Compose inspection checks that require the Docker CLI inside the
  test container and the unavailable institutional corpus; synthetic fixtures
  remain authoritative.
- Read-only HTTP smoke check against the mounted local container returned
  HTTP 200.
- Final-review findings were fixed and scoped re-reviewed; no Critical or
  Important findings remain.
- Authenticated cataloger acceptance was confirmed by the user on 2026-08-07:
  the revised activity treatment is substantially clearer and the release is
  approved for the production-safe branch. Automated browser control was not
  available to capture a screenshot, so this user acceptance is the browser
  evidence for the completion gate.
- Implementation commits: c5c3588, d2a26c0, be2088a, b77cac2, 78903bd,
  c42fe10, cc47112, 77e6b0b, 95461d6, 619c742.
