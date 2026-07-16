Title: Add a durable queue and lifecycle for long-running operations

Scope:
- Persist queued operation definitions, ownership, state, progress, errors, timestamps, cancellation requests, and completion results in SQLite.
- Run queued work outside the browser request so it survives refreshes, disconnects, and application/container restarts.
- Apply the first queue integration to saved-task runs.
- Let users cancel queued or running operations; running work stops safely at a defined checkpoint and never publishes partial output.
- Provide clear queued/running/cancelling/completed/failed/cancelled messaging and progress.
- Retain an auditable operation history and support rollback of an inadvertently applied successful result through the existing immutable job-file version model.
- Define a reusable operation contract for later batch workflows without migrating every existing modifying workflow in this ticket.

Success Criteria:
- A queued saved-task run continues without its browser tab and resumes safely after application/container restart.
- The same operation cannot be executed twice when workers restart or contend.
- Users can request cancellation in every non-terminal state; completion and cancellation races resolve deterministically.
- No failed or cancelled operation publishes a partial job-file version.
- Progress includes current phase, processed and total records when known, and retained error details without unbounded growth.
- Completion is clearly visible in the application, and operation history records actor, inputs, action, result, timing, and relevant counts.
- A successfully applied queued result can be rolled back by creating a new immutable version from the prior version; history is not erased.
- Intent-focused TDD tests, restart/recovery tests, focused integration tests, and code review pass before deployment.

Status: Todo
