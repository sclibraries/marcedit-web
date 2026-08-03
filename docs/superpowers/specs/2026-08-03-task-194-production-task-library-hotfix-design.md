# TASK-194: Production task-library hotfix design

## Objective

Ship the completed task-authoring program, partner-pattern operations, and task
library organization on the existing production service without merging or
activating durable Operations infrastructure.

## Release lineage

Before branch creation, record the deployed repository's clean status, current
branch, and full SHA. The release branch starts from that exact commit. Each
ported ticket records its source commit range and conflict resolution. The
release diff is audited for queue, worker, Operations-page, systemd, sudoers,
proxy, OAuth, and deployment-script changes before it can pass.

TASK-190 through TASK-193 are necessary inputs, together with their already
reviewed task-authoring dependencies. Completion on another branch is not
proof that a port works: every focused and complete test runs again on the
production lineage.

## Runtime boundary

Saved tasks continue to execute synchronously through the existing subprocess
sandbox. The hotfix has no Operations navigation entry, notification bell,
queue submission path, worker health dependency, or durable-result workflow.
The application continues to use the installed `marcedit-web.service`, current
working directory, current environment file, and current sudo permission.

No compatibility mode silently detects services. The branch contains only the
legacy production execution topology, preventing a missing or partially
installed worker from changing behavior.

The legacy deploy script is made branch-aware using a tested fast-forward-only
pull of its currently checked-out release branch, then restarts only the
existing `marcedit-web.service`. It never falls through to `main`, switches
branches implicitly, or manages an unavailable unit. The one-time production
checkout of the approved release branch is a documented user-run Git action,
not an ITS service change.

## Database upgrade and rollback

The folder migration is additive and uses production-compatible SQLite syntax;
it does not use `RETURNING`. Deployment takes a verified database backup before
application restart. Migration runs transactionally and is safe to rerun. The
older application ignores the new table and task column, so code rollback does
not require destructive database rollback. Restoration from backup remains
available for migration corruption or an unrelated database failure.

The release procedure records backup location, release SHA, previous SHA,
health checks, application log checks, and exact rollback commands. Runtime
data directories are never replaced by Git operations.

## Verification gates

1. Confirm exact production lineage and a clean tracked worktree.
2. Review the ported diff against every included ticket and the exclusion list.
3. Run schema migration tests using private tasks, owned shared tasks, shared
   tasks from others, native definitions, legacy definitions, and name clashes.
4. Run synchronous execution tests proving no queue row or Operations link is
   produced.
5. Run the full supported Python 3.9 and production SQLite suite.
6. Run Docker upgrade and rollback tests from the current production schema.
7. Run authenticated browser tests for authoring, import, preview, execution,
   folders, search, sharing, and shared-task collaboration.
8. Report all failures, skips, environmental exclusions, and corpus blockers.
9. Obtain independent code, migration, authorization, and deployment review.
10. Obtain user approval of the final release and rollback SHAs before push.

## Deployment boundary

Pushing the release branch and deploying it are separate explicit actions. The
production deploy workflow pulls the currently checked-out approved release
branch with `--ff-only` and restarts only `marcedit-web.service`. If the
checked-in script attempts to manage unavailable private or worker units, the
release is blocked rather than worked around manually.

No ITS request, service installation, sudoers change, proxy change, or
production directory rename is part of this hotfix. Durable Operations remains
on its separate infrastructure release path.

## Non-goals

- Installing or enabling the durable worker.
- Merging the durable Operations branch into production.
- Redesigning OAuth, Apache, systemd, or production paths.
- Treating a successful push as authorization to deploy.
