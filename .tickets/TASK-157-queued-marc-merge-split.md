Title: Add queued MARC merge and split workflows

Scope:
- Build merge and split as durable queued operations using TASK-156's lifecycle, progress, cancellation, errors, audit history, and result-publishing contract.
- Merge an explicitly ordered list of MARC sources into one output while preserving source and record order.
- Use a source list with a dedicated preview pane showing representative first, middle, and last records with position, 001, 245 title, 100 author, and 020 ISBN.
- Split a MARC source by an optional maximum record count, an optional maximum output size in MB, or both; when both are set, close a part before the next complete record would exceed either limit.
- Preserve MARC record boundaries and report per-part plus total counts.
- In Jobs, publish successful merge and split outputs as new sibling job files with independent history and checkout lifecycle.
- Support direct vendor-file processing and post-batch-edit processing without duplicating MARC transformation logic.

Success Criteria:
- Users explicitly arrange merge sources and can inspect the agreed representative-record preview before submission.
- Merged records preserve the selected source order and each source's internal record order.
- Split parts honor record and size limits without splitting a MARC record; a single record larger than the requested size produces a clear deterministic error.
- Successful Job outputs are new sibling files; failed or cancelled operations publish none of their candidate outputs.
- Progress, cancellation, errors, completion, audit history, and rollback follow TASK-156's operation contract.
- Source, output, per-part, and total record counts are verified and visible.
- Intent-focused TDD tests, focused integration tests, and code review pass before deployment.

Status: Todo
