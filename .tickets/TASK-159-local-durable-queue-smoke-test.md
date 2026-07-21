Title: Smoke-test the local durable operation queue

Scope:
- Validate the current local Docker Compose web and worker services without
  changing application code.
- Submit a small saved-task operation through the real durable queue worker.
- Verify worker heartbeat, operation completion, result publication, and
  absence of duplicate or partial output.
- Record every skipped or unavailable interactive check explicitly.

Success Criteria:
- The local web service and durable operation worker are running and healthy.
- A small queued saved-task operation reaches a terminal completed state
  through the real worker.
- The completed result is published exactly once and its persisted operation
  record retains useful progress and lifecycle evidence.
- Relevant focused tests and runtime checks pass with no hidden failures.

Runtime Findings:
- Docker Compose recreated the web service and started the durable operation
  worker; direct web health and worker heartbeat checks both returned `ok`.
- Live operation 1 processed a seven-record MARC source, completed on attempt
  1 with zero errors, and published exactly one seven-record result artifact.
- Worker logs contain exactly one start and one completion event for operation
  1. After a clean worker restart, the operation remained completed on attempt
  1 and the same single result artifact remained readable.
- Startup repeatedly warns that legacy upload rows 1 and 4 through 11 refer to
  the missing path `data/uploads/roconnell@smith.edu/upload.mrc`. The warning
  does not block queue processing, but it is unresolved local data debt.
- Interactive Operations-page coverage was unavailable because this session
  did not expose the required in-app browser-control backend. No interactive UI
  claim is made.
- Final verification found a health-state contradiction: running the worker's
  `--check` command directly returns `ok`, while Docker Compose reports the
  worker container as unhealthy. TASK-160 corrected the inherited web probe
  and made the recurring worker heartbeat check read-only.

Root Cause:
- Both Compose services use the same Docker image. The image-level healthcheck
  verifies SQLite readiness and then probes Streamlit on
  `http://localhost:8501/_stcore/health`.
- The worker service overrides the image command with
  `python -m marcedit_web.ops.worker` but does not override the inherited
  image healthcheck. It therefore has no process listening on port 8501.
- Docker's health log consistently shows the SQLite probe returning `ok`
  followed by `ConnectionRefusedError` from the Streamlit HTTP probe. The
  worker's own persisted-heartbeat check continues to return `ok`.
- The defect affects both `docker-compose.yml` and
  `docker-compose.pull.yml`; neither defines a worker-specific healthcheck.

Verification:
- Final supported-runtime suite: 1,518 passed, 0 failed, with 36 explicit
  built-image exclusions. The host deployment/Compose suite covered those
  configuration paths with 40 passed and 0 skipped.
- Final live operation 3 completed seven records on attempt 1 with zero errors,
  published exactly one seven-record result, and remained identical after a
  clean worker restart.
- Docker reported both services healthy. Five retained worker health results
  each contained only `ok`; none reran migrations or probed Streamlit.
- Live SQLite `quick_check` and `integrity_check` both returned `ok`.
- TASK-160 final review completed with no Critical, Important, or Minor
  findings and a ready-to-merge verdict.

Status: Completed
