# TASK-158 Docker Benchmark Test Mount Design

Ticket: [TASK-158](../../../.tickets/TASK-158-docker-benchmark-test-mount.md)

## Goal

Make the existing large-batch benchmark contract tests pass in the Docker test
environment without adding test-only tooling to the production image or
weakening the tests with an environment skip.

## Root Cause

`docker-compose.yml` bind-mounts `./tests` into `/app/tests`, allowing pytest to
collect `tests/test_large_batch_benchmark.py`. Those tests load
`scripts/benchmark-large-batch.py` by repository-relative path. The Dockerfile
does not copy `scripts/`, and Compose does not mount it, so both tests fail with
`FileNotFoundError` even though the script exists in the checkout.

## Design

Add one read-only bind mount to the development/test Compose service:

```yaml
- ./scripts/benchmark-large-batch.py:/app/scripts/benchmark-large-batch.py:ro
```

Mounting the single file keeps deployment, installation, and maintenance
scripts out of the container. The Dockerfile and production image remain
unchanged. The benchmark tests remain strict and continue failing if their
required script is unavailable.

## Testing

Extend the Compose configuration contract tests to verify the exact source,
container target, and read-only mode. Follow test-driven development: observe
that assertion fail before editing Compose, then make the minimal mount change.

Run the two large-batch benchmark tests inside Docker, followed by the full
Docker suite. All tests must pass; environment-conditional deploy-file skips
must be reported explicitly.

## Scope Boundary

TASK-158 does not modify benchmark behavior, package scripts into the production
image, change `.dockerignore`, or address unrelated deployment-file skips. Once
verified and reviewed, it is committed independently before TASK-155 resumes.
