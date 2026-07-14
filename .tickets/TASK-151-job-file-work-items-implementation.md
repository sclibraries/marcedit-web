Title: Implement file-centered work items within shared jobs

Scope:
- Implement the approved TASK-150 Job File Work Items design.
- Add durable per-file originals, current versions, history, checkout,
  workflow status, approval, review context, and labeled exports.
- Attach multiple independently processed files to one job and make task,
  edit, batch, restore, history, and export flows file/version aware.
- Migrate existing uploads conservatively and preserve ambiguous snapshots as
  legacy job history.

Success Criteria:
- The complete Routledge two-file acceptance workflow passes end to end.
- Every accepted mutation atomically creates a new current file version;
  failures, stale versions, and lost checkout preserve the prior version.
- Multiple files in one job have separate status, checkout, history, notes,
  approval, and exports.
- Existing uploads migrate idempotently without guessing snapshot ownership.
- Focused TDD tests, the complete suite, interactive workflow verification,
  and code review complete with no unresolved Critical or Important findings.

Design: [Job File Work Items](../docs/superpowers/specs/2026-07-14-job-file-work-items-design.md)

Plan: [Implementation Plan](../docs/superpowers/plans/2026-07-14-job-file-work-items.md)

Status: In-Progress
