Title: Give the Compose queue worker its own healthcheck

Parent: TASK-159

Scope:
- Override the web image's inherited Streamlit healthcheck for the
  `marcedit-web-worker` service in both `docker-compose.yml` and
  `docker-compose.pull.yml`.
- Use the worker's persisted-heartbeat command as the worker-specific health
  signal.
- Make the recurring CLI health probe read-only so it never initializes schema,
  runs migrations, or creates a missing database.
- Preserve the web service's existing SQLite and Streamlit healthcheck and the
  worker's dependency on a healthy web service.
- Add contract coverage that fails if either Compose worker again inherits a
  web HTTP probe.
- Rerun the TASK-159 live queue smoke checks after recreating the services.

Success Criteria:
- Both rendered Compose configurations give `marcedit-web-worker` a
  worker-specific healthcheck based on
  `python -m marcedit_web.ops.worker --check`.
- The web container remains healthy using its existing database and Streamlit
  probes.
- The worker container reaches Docker's healthy state without listening on or
  publishing a Streamlit port.
- A live queued saved-task operation completes exactly once and its single
  result remains readable after a worker restart.
- Focused Compose and durable-queue tests pass with zero hidden failures or
  skips, and code review completes with no unresolved findings.
- TASK-159 is updated with the corrected runtime evidence and completed only
  after all smoke criteria pass.

Status: Completed

Implementation Finding:
- The initial Compose-only override passed its red/green contract test and made
  Docker report both services healthy.
- The subsequent live queue smoke failed during concurrent schema
  initialization with `sqlite3.DatabaseError: database disk image is
  malformed`. After both services stopped, read-only SQLite `quick_check` and
  `integrity_check` each returned `ok`, so no persistent corruption was found.
- The worker `--check` path calls `operations.worker_health()`, which calls
  `db.init_schema()`. Because each Docker health probe is a fresh process, it
  reruns schema seeding and legacy upload migration every 15 seconds. The
  repeated missing-upload warnings in every health result directly confirm
  that the proposed probe is not read-only.
- The approved expanded fix opens the existing SQLite database in read-only
  mode, safely treats a missing database/table as unavailable, observes fresh
  and stale WAL heartbeats, and emits one sanitized error for malformed storage
  or heartbeat timestamps.

Final Verification:
- TDD red confirmed both Compose workers lacked overrides and that `--check`
  created a missing database. A separate red test confirmed malformed heartbeat
  timestamps leaked an exception before the final defensive fix.
- Rendered Compose contracts and host deploy checks: 40 passed, 0 skipped.
- Expanded focused queue/operations suite: 141 passed, 0 skipped.
- Complete Python 3.9 Docker suite: 1,518 passed, 0 failed, 36 explicit
  built-image exclusions; all excluded Compose/deployment paths passed in the
  host suite.
- Both web and worker containers reached Docker's healthy state. The worker
  published no port, retained its healthy-web dependency, and its health log
  contained only successful `ok` results.
- Final live operation 3 completed once with one seven-record result; the same
  operation and artifact remained readable after a worker restart.
- Live SQLite `quick_check` and `integrity_check` both returned `ok`.
- Initial review found two Important coverage gaps and later reviews found two
  Minor malformed-storage diagnostics. All were fixed with focused coverage.
  Final review found no Critical, Important, or Minor issues and marked the
  change ready to merge.
