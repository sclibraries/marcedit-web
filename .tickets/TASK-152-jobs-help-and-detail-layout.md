# TASK-152 — Jobs help and detail layout

## Title

Add practical Jobs help and reduce scrolling on the job detail screen.

## Scope

- Expand the Jobs documentation with a simple cataloger-oriented workflow guide,
  including a multi-file, multi-stage vendor-load example.
- Add an obvious way to reach Jobs help from the Jobs screen.
- Reorganize the job detail screen so common file work is prominent and less-used
  collaboration, review, activity, and administrative controls do not require one
  long stacked page.
- Preserve existing permissions and job behavior.

## Success Criteria

- A cataloger can understand how one job can hold multiple related files and work
  stages, including a recurring vendor-load workflow.
- Jobs help is discoverable from the Jobs screen.
- The job detail screen gives files and current workflow state clear priority and
  substantially reduces routine scrolling.
- Existing file, sharing, review-note, activity, status, and archive capabilities
  remain available according to current roles.
- Tests encode the intended information hierarchy and retained behavior.
- All relevant tests pass with zero skipped tests, and code review is complete.

## Status

Completed

## Design

[Jobs Help and Detail Layout](../docs/superpowers/specs/2026-07-15-jobs-help-and-detail-layout-design.md)

## Plan

[Implementation Plan](../docs/superpowers/plans/2026-07-15-jobs-help-and-detail-layout.md)

## Final verification

- The focused Jobs/deployment suite passed all 37 tests with zero skipped.
- The complete workspace-mounted Docker pytest suite passed all 1,256 tests
  with zero skipped.
- The built `marcedit-web:task-152` image contains `/app/docs/jobs.md`, which
  is readable by the unprivileged `marcedit` user.
- Signed-in owner, editor, and viewer browser verification passed all eight
  planned checks, including two-file visibility through every tab and Personal
  uploads archive protection.
- All per-task reviews and the final whole-branch review completed with no
  unresolved Critical, Important, or Minor findings.
