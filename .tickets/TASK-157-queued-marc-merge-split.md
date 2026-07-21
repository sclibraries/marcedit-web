Title: Add queued MARC merge and split workflows

Dependency: TASK-162 durable large-file ingress and artifact identity

Scope:
- Reuse TASK-156's lifecycle, lease, progress, cancellation, error, and audit
  primitives plus TASK-162/TASK-165's ordered-input and atomic multi-result
  publication primitives. TASK-157 adds merge/split behavior and sibling Job
  publication rather than redefining queue artifact cardinality.
- Merge an explicitly ordered list of MARC sources into one output while preserving source and record order.
- Use a source list with a dedicated preview pane showing representative first, middle, and last records with position, 001, 245 title, 100 author, and 020 ISBN.
- Split a MARC source by an optional maximum record count, an optional maximum output size in MB, or both; when both are set, close a part before the next complete record would exceed either limit.
- Preserve MARC record boundaries and report per-part plus total counts.
- In Jobs, publish successful merge and split outputs as new sibling job files with independent history and checkout lifecycle.
- Support direct vendor-file processing through TASK-162 durable artifact IDs
  and post-batch-edit processing through immutable Job file versions without
  duplicating MARC transformation logic. Streamlit session paths are not valid
  queued inputs.
- Define sibling-output reversal separately from TASK-156 same-file rollback.
  Merge/split reversal must archive or otherwise retire every created sibling
  atomically without pretending it is a prior version of the source file.
- Complete a TASK-157 design before implementation that resolves the remaining
  product contracts: preview computation and immutable-version caching; display
  fallbacks when 001/245/100/020 are absent; whether split limits use bytes or
  MiB and whether equality is allowed; rejection when neither split limit is
  positive; mixed MARC-8/UTF-8 source handling; duplicate-record preservation;
  and per-output publication/download limits. These decisions must be explicit
  and testable rather than inherited accidentally from TASK-156.

Success Criteria:
- Users explicitly arrange merge sources and can inspect the agreed representative-record preview before submission.
- Merged records preserve the selected source order and each source's internal record order.
- Split parts honor record and size limits without splitting a MARC record; a single record larger than the requested size produces a clear deterministic error.
- Successful Job outputs are new sibling files; failed or cancelled operations publish none of their candidate outputs.
- Multiple result artifacts and sibling Job files publish in one all-or-none
  transaction, with retry-safe recovery when filesystem and database commit
  acknowledgement disagree.
- Progress, cancellation, errors, completion, and audit history follow
  TASK-156's lifecycle contract. Reversal uses the explicitly designed sibling
  archive/retirement contract above, not TASK-156 same-file rollback.
- Source, output, per-part, and total record counts are verified and visible.
- Representative preview rendering does not rescan an unchanged source on each
  Streamlit rerun, and missing display fields have a deterministic fallback.
- Split units, equality behavior, required-limit validation, mixed-encoding
  policy, duplicate policy, and output caps match the approved TASK-157 design.
- Intent-focused TDD tests, focused integration tests, and code review pass before deployment.

Status: Todo
