Title: Assemble the task-library production hotfix without durable Operations

Depends On: TASK-190, TASK-191, TASK-192, TASK-193

Design: [Production task-library hotfix](../docs/superpowers/specs/2026-08-03-task-194-production-task-library-hotfix-design.md)

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
  existing `marcedit-web.service` host.

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

Status: Todo
