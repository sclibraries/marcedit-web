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

## Production-safe release branch checkpoint — 2026-08-07

The reviewed application candidate was published without changing `main`:

- Remote branch: `release/task-library-hotfix-2026-08-07`
- Reviewed application SHA: `fa4998282e1e80a7776351f2c540983adc9d4d57`
- Runtime boundary: durable Operations disabled, Operations navigation and
  notifications hidden, saved tasks executed synchronously in the sandbox,
  and no worker required.
- ITS boundary: no systemd, sudoers, Apache/proxy, OAuth, production-directory,
  or service-installation change is included in the deployment request.
- Focused production-boundary suite: 198 passed.
- Hotfix-only Docker topology: 2,760 passed and 18 explicit environment/corpus
  skips, with no failures.
- Authenticated cataloger browser acceptance for the visible activity changes
  was confirmed on 2026-08-07.

This push is a release candidate, not a deployment. Gate 0 must still capture
the live production branch, SHA, service unit, working directory, runtime,
SQLite version, database path, and sudo capability before the deploy script is
run. The production rollback SHA and verified backup destination must be
approved at that time. The remote `main` branch was not modified.

## Production-lineage reconciliation — 2026-08-07

The clean production checkout was confirmed on branch
`legacy-hotfix-production-fixes` at
`1793e4594bcfd5bd85ca9e95200964107dc66085`. That commit and the initial
release candidate diverged after common ancestor `134bc169`; production was
therefore not switched or pulled.

The legacy-only behavior was audited against the current implementation. The
current schema, workspace, and authorization tests supersede obsolete private
UI names and schema-v12 assertions while preserving shared-task editing,
production SQLite job files, job counts, and MARC-order warnings. The audit
found one real compatibility gap: the production regex operation preserved
unmatched subfield text, while the candidate replaced the complete subfield.
The candidate now restores the production contract, including capture
references and validation before mutation.

Verification after remediation:

- Current compatibility and authorization group: 374 passed.
- Hotfix-only Python 3.9 Docker topology: 2,762 passed, 19 explicit
  environment/repository/corpus skips, 0 failed.
- Repository ignore contract: passed against the real checkout; skipped
  loudly only in the built image where `.gitignore` is absent by design.

Before Gate 0 continues, the release history must record `1793e459` as an
ancestor without changing the verified application tree. Production may then
rename its clean local branch to `main` without changing files, capture the
runtime on that branch and SHA, and use the lineage-driven fast-forward deploy.

The first live capture identified `/home/www/html/marcedit-web` and
`marcedit-web.service` correctly but failed closed on the pymarc version probe.
Production has pymarc 5.3.1, which imports correctly but does not expose
`pymarc.__version__`. The probe now uses Python distribution metadata while
still importing pymarc, with a regression test for that exact runtime shape.

The first deployment dry run then rejected Streamlit 1.50's valid annotated
dialog signature because the validator expected the captured string to end at
`)`. Python 3.9 renders the return annotation after that character. The
validator now accepts an optional return annotation while retaining the
existing missing- and malformed-signature rejection tests.

The second dry run failed closed because systemd reported the canonical unit
`marcedit-web.service` while the installed sudoers rule authorizes the
equivalent systemctl target `marcedit-web`. Sudoers matches command arguments
exactly even though systemd accepts either spelling. Deployment now retains
the canonical captured unit for validation and emits the exact authorized
restart target; no sudoers change is required.
