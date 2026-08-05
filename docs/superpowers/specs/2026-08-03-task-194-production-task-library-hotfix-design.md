# TASK-194: Production task-library hotfix design

## Objective

Ship the completed task-authoring program, partner-pattern operations, and task
library organization on the existing production service without merging or
activating durable Operations infrastructure.

## Release lineage

TASK-194 planning is blocked until a fresh read-only runtime-lineage capture is
recorded from production. Earlier operator evidence showed `marcedit-web` active
and enabled, `marcedit-web-private` absent, `/var/www/html/marcedit-web`
resolving to `/home/www/html/marcedit-web`, and the `marcedit` account permitted
to restart only `marcedit-web`. Checked-in Operations-era assets instead target
`marcedit-web-private` and `marcedit-web-worker`; they describe a future
topology and cannot override live evidence.

Gate 0 recaptures, without mutation:

- repository real path, clean status, current branch, and full SHA;
- matching installed units plus active, enabled, fragment, working-directory,
  executable, user, group, and environment-file properties;
- the service user's exact noninteractive sudo allowlist;
- venv Python, Streamlit, pymarc, and installed-package versions;
- Python `sqlite3.sqlite_version` and any installed SQLite CLI version;
- effective database path, file identity, permissions, size, and free space;
- the runtime `st.dialog` signature. Gate 0 requires a recognizable callable
  signature; the post-upgrade deploy preflight separately requires
  `dismissible` after Streamlit reaches `>=1.50,<2`.

The captured active unit, working tree, venv, and database then become explicit
constants in the reviewed implementation plan. If they differ from the prior
evidence, the design is amended before planning. The release branch starts from
the captured exact commit, and deployment refuses a clean branch checkout whose
`HEAD` no longer matches that captured SHA before it pulls the approved release.
Each ported ticket records its source commit range and conflict resolution.

TASK-190 through TASK-193 are necessary inputs, together with their already
reviewed task-authoring dependencies. Completion on another branch is not
proof that a port works: every focused and complete test runs again on the
production lineage.

## Runtime boundary

Saved tasks continue to execute synchronously through the existing subprocess
sandbox. The hotfix has no Operations navigation entry, notification bell,
queue submission path, worker health dependency, or durable-result workflow.
The application uses only the unit, working directory, environment file, and
sudo permission proven by Gate 0; the unit name is not inferred from repository
assets.

No compatibility mode silently detects services. The branch contains only the
legacy production execution topology, preventing a missing or partially
installed worker from changing behavior.

The checked-in deploy script is an Operations-era script, not a legacy script.
TASK-194 replaces its lifecycle explicitly. The production-hotfix script:

1. validates service user, approved branch, clean tree, venv, and captured unit;
2. pulls only that currently checked-out branch with `--ff-only`;
3. verifies `HEAD` equals the explicitly approved release SHA;
4. records the pre-upgrade dependency inventory;
5. upgrades pip and installs `requirements.txt` into the existing venv;
6. verifies Streamlit is `>=1.50,<2` and `st.dialog` exposes `dismissible`;
7. creates and verifies the SQLite backup;
8. runs the application-schema migration/readiness preflight;
9. restarts only the Gate-0 unit and waits for the existing HTTP healthcheck.

It removes worker stop/start, heartbeat expiry/readiness loops,
`marcedit_web.ops.worker --check`, and private-unit assumptions. It retains one
rollbacked SQLite readiness check (`marcedit_web.ops.health`) because that
probe performs the additive application-schema initialization; it does not
check or start a durable worker. It also removes `git pull origin main`. It
never switches branches,
detects a replacement unit, or manages an unavailable service. The one-time
checkout of the approved release branch is a documented user-run Git action,
not an ITS service change.

Gate 0 may capture an older but upgradeable Streamlit version
(`>=1.37,<2`). That capture is recorded as pre-upgrade evidence; the deploy
script must finish the dependency install and pass the
`>=1.50,<2`/`dismissible` preflight before it restarts the service. A missing
or malformed `st.dialog` signature still blocks the capture. Gate 0 never
guesses a runtime executable when `ExecStart` cannot be parsed.

## Database upgrade and rollback

The folder migration is additive and uses production-compatible SQLite syntax;
it does not use `RETURNING`. Deployment uses Python SQLite's online backup API
before migration, then opens the backup independently. Verification requires
`PRAGMA integrity_check` to return `ok`, an exact schema-object inventory,
`PRAGMA user_version`, and row counts for every application table compared with
the live source at the backup checkpoint. The backup path, byte size, and
SHA-256 are recorded. Migration runs transactionally and is safe to rerun. The
older application ignores the new table and task column, so ordinary code
rollback does not require destructive database rollback. A tested restore from
a copied backup remains the response to migration corruption or an unrelated
database failure.

The release procedure records backup location, release SHA, previous SHA,
health checks, application log checks, and exact rollback commands. Runtime
data directories are never replaced by Git operations.

## Verification gates

0. Capture and approve the complete live runtime lineage described above.
1. Confirm exact production lineage and a clean tracked worktree.
2. Review the ported diff against every included ticket and the exclusion list.
   The only permitted deployment-script delta is the explicitly enumerated
   Operations-era-to-hotfix rewrite above; worker, Operations UI, systemd,
   sudoers, proxy, and OAuth changes remain forbidden.
3. Run schema migration tests using private tasks, owned shared tasks, shared
   tasks from others, native definitions, legacy definitions, and name clashes.
4. Run synchronous execution tests proving no queue row or Operations link is
   produced.
5. Run the full supported Python 3.9 and production SQLite suite. Verify the
   installed Streamlit version and dialog-signature preflight before any
   application restart.
6. Run Docker upgrade and rollback tests from the current production schema.
7. Run authenticated browser tests for authoring, import, preview, execution,
   folders, search, sharing, and shared-task collaboration.
8. Report all failures, skips, environmental exclusions, and corpus blockers.
9. Obtain independent code, migration, authorization, and deployment review.
10. Obtain user approval of the final release and rollback SHAs before push.

## Deployment boundary

Pushing the release branch and deploying it are separate explicit actions. The
production deploy workflow pulls the currently checked-out approved release
branch with `--ff-only` and restarts only the Gate-0 unit. If the checked-in
script attempts to manage any other unit, the release is blocked rather than
worked around manually.

No ITS request, service installation, sudoers change, proxy change, or
production directory rename is part of this hotfix. Durable Operations remains
on its separate infrastructure release path.

## Non-goals

- Installing or enabling the durable worker.
- Merging the durable Operations branch into production.
- Redesigning OAuth, Apache, systemd, or production paths.
- Treating a successful push as authorization to deploy.
