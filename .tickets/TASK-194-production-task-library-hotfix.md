Title: Assemble the task-library production hotfix without durable Operations

Depends On: TASK-190, TASK-191, TASK-192, TASK-193

Design: [Production task-library hotfix](../docs/superpowers/specs/2026-08-03-task-194-production-task-library-hotfix-design.md)
Evidence: [Release assembly checkpoint](../docs/superpowers/evidence/task-194-release-assembly.md)

Scope:
- Build a production release branch from the exact deployed commit.
- Capture the live unit, paths, venv, dependency versions, SQLite versions,
  sudo capability, database location, branch, and SHA before writing the
  implementation plan.
- Port the reviewed task-authoring, importer, partner-pattern, folder, and
  search work while preserving synchronous sandbox execution.
- Exclude durable Operations, background workers, new systemd units, and all
  ITS-managed configuration.
- Provide tested upgrade, backup, deployment, and rollback procedures for the
  existing service unit identified by Gate 0.

Success Criteria:
- The branch lineage and included ticket ranges are recorded from the exact
  production SHA; no durable queue or infrastructure commit enters the diff.
- The production runtime-lineage capture resolves the exact unit and capability
  contract; checked-in future-topology assets are not treated as evidence of
  the installed host.
- Saved tasks execute synchronously and no UI path can queue an operation.
- Production-schema upgrade, full Docker, authenticated browser, and rollback
  tests pass with every skip and known limitation reported.
- The existing service and sudo capability are sufficient; no ITS action is
  required for this release.
- The rewritten deploy script retains dependency installation and verifies the
  required Streamlit dialog contract before restarting the captured unit.
- A restorable SQLite backup passes integrity, schema, and table-row-count
  verification before migration begins.
- The final branch, database backup procedure, release SHA, and rollback SHA
  receive user approval before any push or production action.

Planning Gate: Blocked pending current production runtime-lineage capture

Implementation checkpoint:
- Read-only runtime-lineage capture is available and refuses to select a unit
  when more than one matching service is active; no fresh production capture
  has been approved.
- SQLite backup verification now records integrity, schema, user_version,
  row counts, and source/backup hashes.
- The deploy entry point is now lineage-driven, preserves dependency and
  dialog-contract checks, and supports a no-mutation dry run. It refuses dirty
  or branch-drifted checkouts, unsafe release inputs, incompatible Python or
  SQLite versions, and missing noninteractive sudo capability. It never starts
  a worker or invents a unit.
- Release assembly and any non-dry deployment remain blocked until Gate 0
  identifies the live unit, paths, dependency versions, and database.
- The current review worktree still contains Operations-era navigation and
  queue submission inherited from main; the production release branch must be
  assembled from the captured production SHA and remove that topology before
  it can satisfy the synchronous-only boundary.
- The review worktree now routes saved-task execution through a synchronous
  sandbox runner, hides the Operations page and notification bell, and guards
  the Operations script itself. Focused sync-only, navigation, partner, folder,
  runtime, deployment, backup, and migration tests pass. This is still not a
  production release: Gate 0 capture, exact-lineage assembly, Docker, and
  authenticated browser verification remain outstanding.

Status: In-Progress
