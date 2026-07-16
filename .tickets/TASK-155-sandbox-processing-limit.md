Title: Raise the temporary saved-task sandbox processing limit

Scope:
- Fix the immediate production-testing regression where a legitimate large saved-task run exceeds the sandbox's fixed 30-second wall-clock and CPU limits.
- Raise the temporary default CPU and elapsed-processing limits to 300 seconds through one shared definition.
- Replace cataloger-facing "wall-clock" terminology with plain language describing the maximum processing time.
- Preserve the sandbox's bounded handling of runaway or malicious task code.
- Never allow a timed-out partial output to be applied as a job-file version or downloaded as a completed result.
- Keep this change surgical so it can be tested, reviewed, committed, and deployed independently before the durable queue work in TASK-156.
- Leave merge and split behavior to TASK-157.

Success Criteria:
- A legitimate 60,498-record saved-task run has up to 300 seconds to complete instead of inheriting the fixed 30-second default.
- Parent timeout and parent/child CPU enforcement derive from the same 300-second default and cannot silently drift.
- Tests can inject a shorter processing limit without waiting for the production default.
- Runaway task code still terminates within the configured processing limit.
- A timed-out result says "maximum processing time" rather than "wall-clock," remains visibly failed, and cannot be adopted or downloaded as completed output.
- Automated tests encode why legitimate large work receives the temporary larger budget and why partial output remains unusable.
- Relevant focused and regression test suites pass with no silently skipped checks.
- Code review is complete.

Status: Completed

## Implementation Evidence

- The final focused regression suite passed with 72 passed and 0 skipped.
- The final full suite under the project's Python 3.9 Docker environment passed
  with 1,253 passed and 12 skipped. All 12 skips were the existing explicit
  build-context conditions, reconciled as follows:
  - 2 for `deploy/marcedit-web-private.service` not being in the build context.
  - 2 for `docs/deployment.md` not being in the build context.
  - 1 for `deploy/marcedit-web-public.service` not being in the build context.
  - 1 for `deploy/marcedit-web-watchdog.service` not being in the build context.
  - 1 for `deploy/marcedit-web-watchdog.timer` not being in the build context.
  - 2 for `.dockerignore` not being in the build context.
  - 3 for `Dockerfile` not being in the build context.
  None of these environment-conditional skips was counted as passing.
- Static compilation and diff checks completed cleanly.
- TDD and behavior verification confirm one shared 300-second default; parent
  and child CPU soft/hard limits of `(budget, budget + 1)`; normalization of
  exactly `-SIGXCPU` as a timeout; and unchanged handling for ordinary nonzero
  exits. Timed-out partial output has no immediate download or version-adoption
  route and creates no legacy snapshot route. Successful-run behavior remains
  unchanged.
- Review found two Important issues: the legacy snapshot bypass and CPU-boundary
  misclassification. Both were fixed with regression coverage. Final review
  reported no Critical, Important, or Minor findings and `Ready to merge: Yes`.
- Docker verification reused the `marcedit-web` project name because the Docker
  daemon's address pools were exhausted; no Docker resources were manually
  deleted or modified.
