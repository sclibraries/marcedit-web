Title: Make the large-batch benchmark available to Docker tests

Scope:
- Fix the Docker test-environment mismatch where `tests/` is bind-mounted but
  `scripts/benchmark-large-batch.py` is absent from `/app`.
- Bind-mount only the benchmark script read-only for the development/test
  Compose service.
- Keep the production image contents and benchmark test assertions unchanged.

Success Criteria:
- Compose resolves a read-only mount from
  `./scripts/benchmark-large-batch.py` to
  `/app/scripts/benchmark-large-batch.py`.
- The two tests in `tests/test_large_batch_benchmark.py` pass in Docker.
- The full Docker suite has no failures; environment-conditional skips are
  reported explicitly.
- Code review is complete.

## Implementation Evidence

- Host Compose contract: `python3 -m pytest tests/test_docker_compose_config.py -q`
  passed with 7 passed and 0 skipped.
- Full Docker suite: `docker compose -p marcedit-web run --rm marcedit-web
  pytest -q` passed with 1,246 passed and 12 skipped. All skips were
  environment-conditional build-context exclusions:
  - 2 for `deploy/marcedit-web-private.service` not being in the build context.
  - 2 for `docs/deployment.md` not being in the build context.
  - 1 for `deploy/marcedit-web-public.service` not being in the build context.
  - 1 for `deploy/marcedit-web-watchdog.service` not being in the build context.
  - 1 for `deploy/marcedit-web-watchdog.timer` not being in the build context.
  - 2 for `.dockerignore` not being in the build context.
  - 3 for `Dockerfile` not being in the build context.
- Compose validation (`docker compose -p marcedit-web config --quiet`) and the
  implementation-range `git diff --check` completed cleanly.
- The focused benchmark module passed with 2 passed.
- Task review and final functional review found no Critical, Important, or Minor
  code findings. The final review's sole Important finding was this ticket
  lifecycle and evidence update.
- Docker commands reused the `marcedit-web` project name because the Docker
  daemon's address pools were exhausted; no Docker resources were manually
  deleted or modified.

Status: Completed
