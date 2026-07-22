# Legacy Production Hotfix Design

Ticket: [TASK-171](../../../.tickets/TASK-171-legacy-production-hotfix.md)

## Context

Production currently runs commit `134bc16` through the legacy
`marcedit-web.service`. The host does not have the private application or
durable worker units installed, and the `marcedit` account can restart only the
legacy service. Current `main` requires that two-service topology for saved-task
execution, so deploying all of `main` would leave queued work without a worker.

The production checkout path is valid through both `/home/www/html/marcedit-web`
and `/var/www/html/marcedit-web`; path resolution is not the blocker. The
service topology and sudo permissions are the blocker.

## Approach

Create branch `legacy-hotfix-production-fixes` directly from `134bc16` and
adapt only the behavior delivered by TASK-167, TASK-168, TASK-169, and
TASK-170. The implementation will be written against the legacy code rather
than merging or cherry-picking the post-queue branch wholesale.

The hotfix will contain no durable-operation modules, worker integration,
systemd changes, sudoers changes, Apache changes, or deployment-script changes.
The existing synchronous saved-task execution model remains in place.

Alternatives rejected:

- Deploy current `main` under the legacy service: rejected because saved-task
  work is queued and no worker exists to execute it.
- Wait for ITS and deploy all of `main`: operationally clean but does not fix
  the active shared-file production defects promptly.
- Edit production files without a branch: rejected because it creates
  unreviewed drift and makes later reconciliation unsafe.

## Backported Behavior

### SQLite shared-job attachments

Replace every runtime `INSERT ... RETURNING id` identity read in the legacy
job-file implementation with `cursor.lastrowid` from the same connection and
cursor. Preserve transaction boundaries, savepoints, uncertain-commit
reconciliation, filesystem publication, and cleanup behavior.

### Job card/detail consistency

Define `file_count` as non-archived durable `job_files`, matching the default
rows returned by `job_files.list_files()`. Unmaterialized legacy uploads must
not inflate the card. Retained artifacts can migrate after the SQLite fix;
missing artifacts remain absent rather than being fabricated.

### Regex field matching

Add keyword-only `regex=False` and `ignore_case=False` arguments to
`replace_field_subfield_and_indicators`. Regex mode compiles before mutation
and uses `re.search`; case-insensitivity applies only in regex mode. Old calls
and markers remain exact and case-sensitive. The form builder validates enabled
patterns before persistence, and the legacy Save callback exposes validation
through its existing inline error state without calling persistence.

### MARC order diagnostics

Keep View rendering in source MARC directory order. Add a pure helper that
returns at most 20 adjacent descending tag pairs, treats equal tags as valid,
and never mutates the record. View emits one bounded warning before rendering
when inversions exist and remains silent for ascending records.

## Testing and Review

Each behavior is ported with a test-first RED/GREEN cycle on the `134bc16`
codebase. Tests must protect the production SQLite parser failure, member-only
shared-file visibility, card/detail equality, regex compatibility and
atomicity, callback-level inline validation, source-order preservation, and
bounded View warnings.

The branch gate is the complete repository suite in the existing
network-disabled Python 3.9 image, compilation of application and tests,
`git diff --check`, a prohibited-scope diff audit, and independent review with
no unresolved Critical or Important findings.

## Deployment and Rollback

The branch will be pushed explicitly without changing `origin/main` or any
other worktree branch. Production must not run `scripts/deploy.sh` for this
hotfix because the legacy script pulls `origin/main`.

Deployment will use explicit commands to fetch and switch to the hotfix branch,
fast-forward only from that branch, refresh the existing virtual environment,
restart `marcedit-web.service` through the already-authorized sudo command, and
verify the Streamlit health endpoint. The untracked `data/snapshots/` directory
and all ignored data remain untouched.

Rollback will switch the production checkout back to detached commit
`134bc16`, refresh dependencies if required, restart the legacy service, and
verify health. No database downgrade is promised; schema changes used by these
four fixes are additive/idempotent and already exist in the legacy application
line.

When ITS can install and validate the private application and worker units,
updated sudoers, and service group choices, production can transition from the
hotfix branch to `main` under a separate deployment plan.
