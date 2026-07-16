# TASK-155 Sandbox Processing Limit Design

Ticket: [TASK-155](../../../.tickets/TASK-155-sandbox-processing-limit.md)

## Goal

Allow legitimate large saved-task runs during production testing to execute for
up to five minutes while retaining bounded sandbox behavior and preventing a
timed-out partial file from being mistaken for a completed result.

This is an intentionally temporary, independently deployable fix. TASK-156 will
replace browser-bound long runs with a durable queued-operation lifecycle.
TASK-157 will add queued MARC merge and split workflows.

## Root Cause

`run_tasks_subprocess` currently defaults to a 30-second parent timeout. The
parent applies a 30-second `RLIMIT_CPU`, and the inlined child driver repeats the
same hard-coded CPU limit. The child streams records to its output as they are
processed. When the parent timeout fires, that output is a valid-looking prefix
of the input rather than a complete transformation.

The reported run processed 43,762 of 60,498 records before the fixed limit
stopped it. TASK-147 made large-batch data flow disk-backed and bounded memory,
but deliberately preserved the synchronous sandbox limits. The observed failure
is therefore the configured execution budget, not record materialization or a
memory failure.

## Scope

TASK-155 changes only the saved-task sandbox processing limit, timeout failure
copy, and timeout-result action gates. It does not introduce a queue, worker,
chunking, background execution, resumability, merge, split, or a new deployment
setting.

The default processing limit will be 300 seconds. The production service admits
two heavy batch operations and has a 200% CPU quota, so the worst temporary case
is two runaway sandbox processes occupying both batch slots and the available
CPU for five minutes. Each sandbox remains subject to its existing 512 MB
address-space limit, and the service retains its 2 GB memory ceiling. A longer
limit is rejected because it approaches the reverse proxy's 600-second timeout
and would block both operation slots for too long.

## Limit Ownership and Enforcement

The sandbox module will define one default processing-limit constant with a
value of 300 seconds. `run_tasks_subprocess` will continue accepting an injected
shorter limit so tests and specialized callers can bound a run without waiting
five minutes.

The effective limit for each invocation will govern all three enforcement
points:

1. the parent process's elapsed-time timeout;
2. the CPU resource limit applied before executing the child; and
3. the defensive CPU resource limit set inside the inlined child driver.

The child will receive the effective limit explicitly as a command-line
argument. The pre-execution limit callback will be created for that invocation
instead of relying on a separate hard-coded module value. This keeps parent and
child enforcement aligned when a test passes a short limit.

The CPU limit must be a positive whole number because `setrlimit` uses seconds.
An injected fractional elapsed-time limit will be rounded up for CPU enforcement
while the parent retains the exact elapsed timeout. This preserves fast timeout
tests without accidentally setting a zero-second CPU limit.

## Successful Run Flow

A run that completes within the effective processing limit keeps the existing
behavior:

1. stream the active records into the sandbox input;
2. execute the selected tasks;
3. count and compare the complete output;
4. show diff and error review;
5. allow an explicit download or immutable job-file version adoption; and
6. record run history and audit details.

No new success-path UI or storage model is introduced.

## Timeout Flow and User Messaging

When the effective limit is reached, the parent terminates the sandbox and
records the existing structured timeout state. Partial output may be counted for
diagnostic history, but it is not a publishable result.

Cataloger-facing text will avoid implementation terminology:

- status: `Run reached the maximum processing time`
- message: `This run exceeded the 5-minute processing limit and stopped before
  all records were completed. No partial output was applied or made available
  for download.`

The timed-out result will not compute or present a complete diff. It will not
show the download preparation action, and the existing job-file adoption action
will remain unavailable. Audit and run history will continue recording input
count, partial output count, exact error count, timeout state, task names, user,
and sandbox return code.

Low-level logs and structured error codes may retain `sandbox-timeout` because
those are stable operator/developer interfaces. Only cataloger-facing copy is
changed.

## Testing

Tests will encode the business intent, not merely the new number:

- A sandbox unit test will prove the default effective processing limit is 300
  seconds at the parent and both CPU enforcement points.
- A short injected limit will prove runaway code is still terminated promptly
  and that the injected CPU limit reaches the child.
- A Tasks render test will prove catalogers see `maximum processing time` and do
  not see `wall-clock` in timeout status or guidance.
- Timeout-result tests will prove neither download preparation nor job-file
  version adoption is offered for partial output.
- Existing successful-run tests will prove completed output retains its diff,
  download, adoption, audit, and run-history behavior.

Focused verification will cover sandbox execution, Tasks rendering and export,
job-file adoption, audit, and run history. The full test suite must then pass
with any skipped tests reported rather than silently treated as coverage.

## Deployment Boundary

TASK-155 ends after review, verification, commit, and the user's production
deployment handoff. The 300-second limit is a testing-phase bridge, not the final
long-running-operation architecture. TASK-156 begins only after TASK-155 is
accepted in production.
