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
- Deployment refuses a dirty captured checkout, branch drift, or commit drift
  before pulling the approved release branch, then verifies the approved
  release SHA immediately after the pull before any dependency or database
  operation.
- The production runtime-lineage capture resolves the exact unit and capability
  contract; checked-in future-topology assets are not treated as evidence of
  the installed host.
- Saved tasks execute synchronously and no UI path can queue an operation.
- The local hotfix Compose file starts only the web service; the durable worker
  remains confined to the separate infrastructure Compose topology.
- Production-schema upgrade, full Docker, authenticated browser, and rollback
  tests pass with every skip and known limitation reported.
- The existing service and sudo capability are sufficient; no ITS action is
  required for this release.
- The rewritten deploy script retains dependency installation and verifies the
  required Streamlit dialog contract before restarting the captured unit.
- Gate-0 may record an upgradeable `>=1.37,<2` Streamlit install when it
  exposes a recognizable `st.dialog` signature, but restart is forbidden
  until the install reaches `>=1.50,<2` with `dismissible`.
- A restorable SQLite backup passes integrity, schema, and table-row-count
  verification before migration begins.
- The final branch, database backup procedure, release SHA, and rollback SHA
  receive user approval before any push or production action.

Planning Gate: Satisfied by the approved live runtime-lineage capture

Completion checkpoint:
- Production lineage was reconciled from rollback SHA `1793e459`; the tested
  candidate retained the exact verified application tree while recording the
  live production commit as an ancestor.
- Gate 0 identified `/home/www/html/marcedit-web`, Python 3.9, pymarc 5.3.1,
  Streamlit 1.50.0, SQLite with partial-index support, the production database,
  `marcedit-web.service`, and the existing suffixless sudo restart target.
- The database and audit backup was created and independently verified at
  `/home/marcedit/backups/marcedit-web/2026-08-07-ac4182b` before schema health
  ran.
- Production is on `main` at `1dfc10c`, the checkout is clean, the existing
  service is active, and the local health endpoint returns `ok`.
- Saved tasks remain synchronous; durable Operations navigation,
  notifications, and worker lifecycle are not exposed by this release.
- The authoritative hotfix-only Python 3.9 Docker run passed with 2,762 tests,
  19 explicit environment/repository/corpus skips, and no failures. Final
  deployment-contract verification passed with 60 tests.
- Authenticated live browser verification was confirmed by the cataloger on
  2026-08-07. No ITS-managed configuration was changed.

Status: Completed
