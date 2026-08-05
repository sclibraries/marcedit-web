# TASK-194 release assembly checkpoint

Date: 2026-08-04

## Current candidate

The reviewed implementation is on branch `task-192-194-design`. The current
working tree contains uncommitted remediation changes in this environment, so
it is not a production release candidate yet. The sync-only boundary was
introduced in `67cfb48` and is verified by
the private-navigation, sidebar, direct Operations-page guard, and saved-task
runner tests.

The branch is not yet a production release. The known legacy hotfix branch
`legacy-hotfix-production-fixes` currently ends at `1793e459`; that SHA is a
candidate lineage reference only, not a fresh Gate-0 production capture.

## Ported ticket evidence

The current candidate contains the reviewed implementation and tests for:

- TASK-190: external parser, proven adapters, migration drafts, and the
  example-task compatibility fixtures.
- TASK-191: partner corpus fixtures, provenance checks, and the checked-in
  corpus report.
- TASK-192: bounded pymarc partner operations, explicit policies, batch
  accounting, fail-closed adapter dispatch, and guided blockers for the
  remaining unproven partner ranges. Contiguous 856/945–949 adapters are not
  yet accepted because their looping dependency is absent from the corpus.
- TASK-193: additive folder schema, stable task rename/move, shared/private
  authorization, collaborative shared-task edits, fail-closed preservation of
  shared hand-written bodies, search, audited organization actions, and a
  fail-closed native-definition form round-trip for the supported v1 subset.
- TASK-194: read-only lineage capture, verified backup, lineage-driven deploy
  preflight, and the synchronous hotfix boundary.

## Excluded at runtime

The hotfix does not expose the Operations page, notification bell, sidebar
queue summary, durable submission from Tasks, or the Operations page through a
direct route. Saved tasks run through the synchronous subprocess sandbox and
leave no durable operation row.

The repository still contains durable-Operations modules inherited from the
main development line. They are intentionally inert in this hotfix path; a
release assembled from the exact production SHA must record whether those
modules are retained as inert code or removed from the release diff.

## Gates still open

1. Capture and approve the live Gate-0 runtime lineage on the production host.
2. Assemble and review the release branch from that exact SHA.
3. Run authenticated browser verification under the captured Python, SQLite,
   and Streamlit contract. The local Python 3.9 hotfix Compose suite is
  complete: 2,515 passed, 18 explicit skips, 0 failed; production runtime
   capture remains open.
4. Obtain release and rollback SHA approval before push or deployment.
