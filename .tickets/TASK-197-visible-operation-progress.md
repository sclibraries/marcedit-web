Title: Make long-running operation progress visible in-page

Design: [Visible operation progress](../docs/superpowers/specs/2026-08-06-visible-operation-progress-design.md)

Scope:
- Replace spinner-only feedback for long Quick operations with a visible
  in-page status panel.
- Reuse existing progress callbacks and `st.status` conventions for Quick
  Find and replace, focused Quick field changes, and specialized Quick batch
  operations.
- Preserve operation semantics, sandbox boundaries, and existing completion
  and error handling.

Success Criteria:
- A cataloger sees a clear in-page activity message while a long operation is
  preparing, previewing, applying, or finalizing.
- Where record progress is available, the panel shows processed and total
  records with a progress bar.
- Completion, cancellation, and failure leave a readable final status.
- Existing operation results, stale-preview rules, and downloads are unchanged.
- Tests cover status lifecycle and progress updates without requiring a
  browser.

Status: In-Progress
