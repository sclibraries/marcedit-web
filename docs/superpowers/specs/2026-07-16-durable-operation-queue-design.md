# TASK-156 Durable Operation Queue Design

Ticket: [TASK-156](../../../.tickets/TASK-156-durable-operation-queue.md)

Date: 2026-07-16

## Goal

Move long-running saved-task runs out of the Streamlit request process and into
a durable queue. A submitted run must continue after the user leaves the page,
survive application and worker restarts, expose useful progress and errors,
support cancellation, retain an audit history, and never publish partial output.

The first release processes one queued operation at a time. It supports saved
tasks against either a Job file or a Quick Load file. The operation contract is
deliberately reusable by TASK-157 for MARC merge and split workflows, but merge,
split, and migration of other batch tools are outside this ticket.

## Decisions

- Use a separate polling worker backed by the application's existing SQLite
  database and WAL mode.
- Run one operation at a time in the first release.
- Deploy the worker as a separate systemd service and a separate Compose
  service using the same application image, environment, database, and data
  volume as the private application.
- Capture immutable input and an immutable ordered snapshot of selected task
  definitions when the operation is submitted.
- Process the input in bounded record chunks. The existing five-minute sandbox
  limit applies to each chunk, not to the overall operation.
- On worker interruption, discard the unpublished attempt and restart the
  operation from its immutable input. This release does not resume from a
  record-level checkpoint.
- Publish a result only after every chunk completes and the combined MARC file
  passes final validation.
- Keep Job results as reviewable candidates until a user explicitly applies
  one as a new immutable Job file version.
- Keep Quick Load results downloadable and reopenable without changing the
  original Quick Load input.
- Provide persistent in-app alerts through a Material-styled notification bell;
  do not send email.
- Retain operation metadata and audit events indefinitely. Retain Quick Load
  files and unapplied Job candidates for 30 days by default. Applied immutable
  Job versions do not expire.

## Architecture

The private Streamlit application is the command and monitoring surface. It
validates authorization, creates operations, shows progress and history,
accepts cancellation requests, acknowledges notifications, and performs the
separate Job-version apply or rollback actions. It never executes queued task
bodies.

SQLite is the source of truth for operation definitions, state, leases,
progress, errors, artifacts, events, notification acknowledgement, and worker
health. Database transactions arbitrate every state transition.

The worker polls SQLite, atomically claims one queued operation, creates an
attempt workspace, invokes the existing subprocess sandbox for bounded chunks,
reports progress, validates the complete candidate, and commits the result. A
random token identifies each lease attempt. Only the current token may update
progress or complete an operation.

Durable files live below a dedicated operations root inside `data/`. Attempt
files use an attempt-specific temporary directory and are never exposed by the
UI. Final result paths become visible only after a successful completion
transaction. An interrupted rename or transaction may leave an unreferenced
file, but it cannot become a result; idle cleanup removes such orphans.

## Components

### Operation service

A focused library module owns submission, authorization, queries, lifecycle
transitions, leases, cancellation, notification acknowledgement, and cleanup
eligibility. Render code calls this service rather than issuing queue SQL.

Submission performs the following work before inserting a `queued` operation:

1. verifies the user and source access;
2. resolves the exact source file version or Quick Load file;
3. reads and validates each selected task in its user-selected order;
4. snapshots each task name and body into a versioned request payload;
5. copies a Quick Load input into durable operation storage, or records the
   exact immutable Job file version as the input artifact; and
6. records the initial audit event.

Editing, renaming, sharing, or deleting a saved task after submission cannot
change queued work.

### Worker

`marcedit_web.ops` gains a long-running worker entry point suitable for
systemd, Compose, and direct development use. The worker initializes the schema,
updates its health heartbeat, polls for work, recovers expired leases, claims at
most one operation, and sleeps for a bounded interval while idle.

The worker runs task code only through the existing subprocess sandbox. The
worker process itself performs deterministic routing, file streaming, MARC
validation, state transitions, and retries; no model is used for these tasks.

### Chunked saved-task runner

The default chunk size is 5,000 records and is configurable through a validated
deployment setting. The worker streams the immutable input into chunk files
without materializing the entire batch. Each chunk receives the same ordered
task snapshot and the existing five-minute sandbox safety limit.

The sandbox child writes bounded error details and a small progress sidecar.
The worker uses a controllable subprocess instead of a single blocking
`subprocess.run` call so it can:

- refresh the operation lease;
- read processed-record progress;
- check for cancellation approximately once per second; and
- terminate the complete sandbox process group when required.

Progress writes to SQLite are throttled to avoid a transaction per record.
Successfully validated chunk output is appended to the attempt's aggregate
candidate. A chunk timeout, nonzero sandbox exit, malformed chunk, or unexpected
record count fails the attempt. The aggregate remains private until final
validation succeeds.

The five-minute limit is therefore a per-chunk runaway-code boundary. The
overall queued operation may run for as many chunks as needed. This follows the
worker/job separation used by queue systems such as Yii2 Queue while adding
application-level chunking suited to large MARC files.

### Operations page and global alerts

A private **Operations** page appears in the Start navigation group. It shows
queued, running, needs-attention, and completed counts followed by operation
cards or rows containing:

- state and current phase;
- processed and total records, percentage, and elapsed time;
- source Job/file/version or Quick Load filename;
- selected tasks in execution order;
- submitter and timestamps;
- exact error count and bounded error details;
- recovery and cancellation events;
- result review, download, reopen, apply, and rollback actions as applicable;
  and
- artifact expiration date.

The page refreshes while visible and active work exists. Other pages do not
continuously poll, but the existing shared sidebar status links to Operations
and shows compact queued/running/attention counts.

The global authenticated header adds a notification control beside Account.
It uses the application's existing Material icon convention:
`:material/notifications:` and `:material/account_circle:` with matching size,
spacing, theme, and button treatment. Emoji and custom icon artwork are not
introduced.

The submitter receives an unread alert when an operation:

- completes successfully;
- completes with record errors;
- fails; or
- is cancelled by another authorized user.

The first page visit after a new terminal result shows a prominent success or
error notice. The bell popover retains unread outcomes until the user marks one
or all as read. Recovery and ordinary progress remain in the operation timeline
without generating noisy alerts.

## Durable Data Model

The additive SQLite migration introduces these logical entities.

### `operations`

One row contains the operation kind and request schema version; submitter;
optional Job and Job-file relationships; lifecycle state and phase; request
snapshot JSON; processed, total, changed, output, and error counts; timestamps;
cancellation requester and time; terminal summary; notification
acknowledgement; current attempt; lease owner, token, heartbeat, and expiry; and
artifact expiration.

The first supported operation kind is `saved-task-run`. The request payload has
an explicit schema version and contains the exact ordered task snapshots and
execution settings required by the worker.

### `operation_artifacts`

Artifacts belong to an operation and identify their role, durable path,
filename, record count, byte count, creation time, and optional source Job file
version. The first release needs input and final-result roles. The one-to-many
shape permits TASK-157 to represent multiple merge inputs or split outputs
without changing the operation lifecycle tables.

Attempt-specific temporary files do not become user-visible artifacts until
completion. Existing immutable Job version files are referenced, never copied
or deleted by artifact retention.

### `operation_events`

Append-only events record actor, event kind, concise message, structured bounded
details, and timestamp. Events include submission, claim, phase changes,
recovery, cancellation request, cancellation, failure, completion, result
application, rollback, acknowledgement, and retention cleanup. Progress is
stored on the operation row rather than generating an event per update.

### `operation_errors`

The operation row retains the exact total error count. This child table retains
only the existing bounded maximum of representative record errors, including
record index, task, stable code, and safe message. Chunk-relative indices are
translated to input-wide record indices before storage.

### Worker health

A small singleton worker-health row stores worker identity, process start time,
last heartbeat, current operation when present, and software version. This is
separate from an operation lease so the UI can distinguish a normally waiting
queue from a stopped worker even while no operation is running.

## Lifecycle and Concurrency

Persisted states are `queued`, `running`, `cancelling`, `completed`, `failed`,
and `cancelled`.

- Submission creates `queued`.
- A worker uses `BEGIN IMMEDIATE` to atomically claim the oldest eligible row,
  set `running`, increment the attempt number, and assign a fresh lease token.
- A successful worker moves through preparing, processing, validating, and
  publishing phases before atomically setting `completed`.
- Expected execution or validation failure sets `failed`.
- Cancelling a queued operation atomically sets `cancelled` without starting it.
- Cancelling a running operation sets `cancelling`; the worker terminates the
  sandbox process group, removes attempt output, and sets `cancelled`.
- An expired `running` lease is recorded as a recovery event and requeued with a
  user-facing "restarted after interruption" message.
- An expired `cancelling` lease becomes `cancelled`; no replacement attempt is
  started.

Atomic claim prevents contending workers from owning the same attempt. Recovery
may intentionally re-execute an interrupted operation from the beginning, but
only the current lease token can commit progress or a result. A stale worker
cannot publish or transition the operation.

Cancellation is deterministic. A cancellation transaction that changes
`running` to `cancelling` wins before completion begins. The completion
transaction succeeds only when the row is still `running`, has no cancellation
request, and carries the worker's current lease token. Once completion commits,
the operation is terminal and cannot be cancelled; the user may ignore an
unapplied result or roll back an applied Job result.

## Permissions

- The submitter may cancel their own non-terminal operation.
- A Job owner may cancel an operation for a file in that Job.
- An application admin may cancel any operation.
- Other editors and viewers may not cancel another user's operation.
- Operation visibility follows source access. Quick Load operations are private
  to their submitter. Job operation visibility follows current Job access.
- Applying a Job result requires owner/editor access, the existing Job-file
  checkout, and the exact source version still being current.
- Rollback requires the same mutation authority and checkout protections as any
  other immutable Job-file version adoption.

All authorization is rechecked at action time. Access captured at submission is
not treated as permanent authorization to cancel, apply, download, or roll back.

## Result Handling and Rollback

### Job files

Completion produces a retained candidate associated with the exact source
version. Users can inspect its summary, errors, validation, and diff before
applying it. Apply remains a separate user action and calls the existing atomic
Job-file version adoption boundary.

If the source version is no longer current, apply is blocked so queued work
cannot overwrite a newer version. The candidate remains reviewable and
downloadable until it expires.

Applying creates a new immutable version whose parent is the queued operation's
source version and records the operation in file and Job activity. Rollback
does not move the current pointer backward or delete history. It copies the
prior version's bytes into another newly numbered immutable version, records
who performed the rollback and why, and preserves the applied version in
history.

### Quick Load

Completion retains the original input and result as operation artifacts. The
user may download the result or explicitly reopen it into Quick Load. Reopening
does not overwrite the original artifact. "Rollback" for an unapplied Quick
Load result means reopening the original input.

## Errors, Safety, and Logging

Record-level task exceptions retain the sandbox's cardinality-preserving error
path. The operation may complete with warnings, an exact error total, and
bounded representative details.

Operation-level failures include chunk timeout, sandbox launch or exit failure,
invalid task snapshot, unreadable input, malformed output, unexpected output
cardinality, lease loss during publication, and durable-storage failure. Failed
and cancelled attempts never expose partial output.

Deterministic task failures are not automatically retried. Infrastructure loss
uses the approved recovery path and starts a fresh attempt from immutable input.

Two logging layers serve different audiences:

- SQLite operation events provide user-facing audit history.
- Structured Python logs go to systemd journal or container stdout for
  operators.

Operational logs include operation id, attempt, chunk number, worker id,
lifecycle transition, durations, counts, lease events, sandbox exits, timeouts,
validation, publication, cleanup, and stack traces for internal failures. The
operation id is the correlation key between user history and server logs.
Captured sandbox stderr is bounded.

Logs and event details must not contain MARC record contents, complete task
bodies, OAuth data, proxy secrets, or other credentials. The immutable task
snapshot remains protected in the database and is not copied into ordinary log
messages.

## Retention

- Operation rows, events, counts, and bounded error metadata are retained
  indefinitely unless a future explicit administrative policy changes that.
- Quick Load input/result artifacts and unapplied Job candidates expire after
  30 days by default. The period is deployment-configurable and shown to users.
- Applied Job versions and the Job activity that references them do not expire.
- Existing Job version paths referenced as operation inputs are not owned by the
  queue cleanup process.
- Idle worker maintenance removes expired queue-owned artifacts and orphaned
  attempt directories while recording cleanup events. Cleanup failure is logged
  and retried later; it does not corrupt operation history.

## Deployment

Production gains `deploy/marcedit-web-worker.service`. It uses the `marcedit`
user and group, repository working directory, `.env`, private database path,
`data/` write access, resource isolation, filesystem protections, and restart
policy consistent with `marcedit-web-private.service`. It runs independently of
the Streamlit process so an application restart does not stop queued work.

Compose gains one worker service using the same image and bind-mounted source,
configuration, and `data` volume. Only the Streamlit service publishes a port.

Install, sudoers, deploy, preflight, and deployment documentation are updated
for the worker. A deployment stops the worker, updates code and dependencies,
starts the private application so the additive schema migration completes,
then starts the worker. This ordering prevents old worker code from writing
during migration. Any interrupted operation is recovered from its immutable
input.

Verification checks both the Streamlit health endpoint and a fresh worker
heartbeat. Operators receive commands for worker status and journal inspection.
The public tier neither starts queue work nor exposes Operations, alerts, task
snapshots, or queue artifacts.

## Testing

Intent-focused tests will cover:

- additive schema migration and all constraints and indexes;
- immutable ordered task snapshots and durable Quick Load input capture;
- state transitions and invalid-transition rejection;
- submitter, Job owner, editor, viewer, and admin cancellation permissions;
- atomic claims under competing workers;
- lease expiry, recovery, stale-token rejection, and interruption restart;
- deterministic cancellation/completion races;
- process-group termination and absence of published cancelled output;
- chunk streaming, ordered-task equivalence, aggregate validation, and
  input-wide error-index offsets;
- progress throttling, processed/total counts, and bounded error retention;
- per-chunk timeout without an overall five-minute operation cap;
- no result publication after timeout, nonzero exit, malformed output, record
  count mismatch, cancellation, or lease loss;
- Job result review, stale-source apply rejection, immutable application, and
  immutable rollback;
- Quick Load download, reopen-result, and reopen-original behavior;
- notification count, first-return notice, acknowledgement, and Material icon
  integration;
- worker-unavailable messaging based on health heartbeat;
- 30-day artifact cleanup without deleting audit metadata, source Job versions,
  or applied versions;
- safe structured logging without record or task-body leakage;
- systemd unit validation and Compose configuration; and
- a realistic large-file benchmark demonstrating that a run exceeding five
  total minutes can complete through bounded chunks.

Focused tests run first during TDD. The complete Docker suite must pass with any
skips explicitly reported. An independent code review is required before the
ticket is marked Completed, committed, and handed off for production deployment.

## Out of Scope

- MARC merge and split workflows, which belong to TASK-157.
- Moving every existing batch operation to the queue.
- Redis, Celery, RabbitMQ, or another external broker.
- Multiple simultaneously executing operations in the first release.
- Record-level checkpoint resume after a worker interruption.
- Automatic retries for deterministic task, timeout, or validation failures.
- Email, SMS, or desktop push notifications.
- Changing the five-minute sandbox safety limit established by TASK-155.
