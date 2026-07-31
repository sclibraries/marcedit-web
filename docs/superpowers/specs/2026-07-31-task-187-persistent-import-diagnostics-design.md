# TASK-187 Persistent Import Diagnostics Design

**Ticket:** [TASK-187](../../../.tickets/TASK-187-persist-import-diagnostics.md)

**Status:** Approved

## Purpose

Task import currently renders warnings and then immediately reruns the
Streamlit page. The rerun removes the warning before a cataloger can read the
unresolved instructions. The importer is correctly fail-closed; the defect is
that its result is transient.

TASK-187 preserves import outcomes through reruns without changing which
external instructions are convertible.

## Goals

- Keep every import outcome visible until dismissed or replaced.
- Show unresolved instructions and archive-entry failures in a reviewable
  bounded form.
- Preserve current fail-closed conversion and storage behavior.
- Prevent an old result from being mistaken for the result of a later import.

## Non-Goals

- Adding new MarcEdit instruction mappings.
- Persisting import results in SQLite.
- Sharing results across users or browser sessions.
- Changing task storage, execution, authentication, or deployment.

## Result Model

Import processing produces a typed session-scoped result with:

- overall status: `success`, `partial`, or `rejected`;
- uploaded display filename;
- imported task names;
- per-archive-entry status and message;
- rejection category: quota, unresolved instructions, archive validation, or
  unexpected exception;
- at most 20 displayed unresolved source instructions;
- the count of additional omitted instructions; and
- a safe actionable summary.

The result contains no uploaded archive bytes, credentials, stack traces, or
cross-user identifiers. Unexpected exceptions retain their detailed server
log and audit event; the session result contains only the bounded user-facing
message already permitted by the application.

## Lifecycle

The import callback clears any previous result before starting. It computes
the complete outcome, stores it under one Tasks-specific session-state key,
and then permits the existing full-app rerun.

The Build & import page renders the stored result after rerun. A **Dismiss**
button clears it. Ordinary widget reruns do not clear it. A new import replaces
it atomically. Leaving or resetting the task-authoring lifecycle clears it so
an unrelated later visit cannot display stale diagnostics.

## Rendering

- Success uses `st.success` and lists imported task names.
- Partial archive success uses a summary plus per-entry successes and warnings.
- Rejection uses `st.warning` for expected unsupported input and `st.error`
  for quota, archive-integrity, or unexpected failures as currently classified.
- Unresolved source lines render as text/code, not executable controls.
- More than 20 lines produces an explicit omitted-count caption.
- Every result has **Dismiss**.

## Failure Handling

Building or rendering a result must not weaken import safety. No task row is
saved when current conversion policy rejects it. A failure to render one entry
does not erase the stored overall result. Malformed session-state payloads are
discarded fail-closed with a logged diagnostic rather than crashing Tasks.

## Testing

Tests first reproduce the disappearing result across the import-triggered
rerun. Focused cases cover successful text import, rejected text import,
successful archive import, mixed archive outcomes, quota rejection,
unexpected exceptions, replacement by a later attempt, Dismiss, and lifecycle
reset. Tests assert the 20-line bound and omitted count.

The complete mounted-source Docker suite reports every skip. Independent
review must find no unresolved Critical or Important issue.

## Rollout

This is application-only Streamlit state. It requires no database migration,
service file, route, proxy, worker, cron, or ITS change.
