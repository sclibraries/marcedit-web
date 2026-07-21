Title: Exclude local runtime data from production images

Scope:
- Prevent Docker builds from copying local SQLite databases, uploads, job-file
  versions, operation artifacts, audit logs, task files, and other generated
  runtime state through `COPY data ./data`.
- Allow only the tracked bootstrap data files `data/.gitkeep` and
  `data/marc-rules.txt` into the build context.
- Preserve runtime creation and ownership of writable `/app/data` directories.
- Rebuild and smoke-test the source-baked release candidate before any push.

Success Criteria:
- `.dockerignore` excludes all `data/*` content by default and explicitly
  re-includes only `data/.gitkeep` and `data/marc-rules.txt`.
- Automated coverage fails if runtime data can silently re-enter the build
  context.
- A fresh image contains no local database, upload, job-file, operation, audit,
  or user-task artifacts.
- The fresh image retains `data/marc-rules.txt`, initializes an empty database,
  and passes web/worker health checks.
- Relevant focused and complete tests pass with every skip reported, and code
  review completes with no unresolved findings.

Status: Completed

Release Finding:
- The pre-push release build sent a 444.65 MB context and produced a 438.8 MB
  image containing 422 MB under `/app/data`, including local MARC and queue
  artifacts. Commit and push were halted before any repository mutation.

Final Verification:
- TDD red confirmed the prior `.dockerignore` did not establish a runtime-data
  deny-by-default rule. The focused Docker configuration suite passed after the
  allowlist was added.
- A no-cache source build sent a 13.49 KB context and produced a 172,300,563-byte
  image. `/app/data` was 112 KB and contained only `data/.gitkeep` and
  `data/marc-rules.txt`; no database, job files, operation artifacts, uploads,
  audit files, or user task files were present.
- A first isolated smoke attempt omitted the production Compose absolute data
  paths and failed when the worker resolved an operation workspace relative to
  its process directory. This was a smoke-harness configuration error, not an
  image failure. The temporary volume was reset and the production environment
  paths were supplied exactly for the authoritative run.
- With the production data-path environment, fresh web and worker containers
  from the source-baked image both became healthy. A three-record synthetic
  queued operation completed on attempt 1 with zero errors, published one
  three-record result, and remained identical after a clean worker restart.
- The fresh SQLite database returned `ok` for both `quick_check` and
  `integrity_check`. The retained worker health results contained only `ok`.
- Host deployment and rendered Compose checks: 41 passed, 0 skipped. Complete
  Python 3.9 Docker suite: 1,518 passed, 0 failed, 37 explicit built-image or
  unavailable-Docker exclusions; all excluded repository configuration paths
  passed in the host suite.
- Final independent review found no Critical, Important, or Minor issues and
  marked the release changes ready to merge.
