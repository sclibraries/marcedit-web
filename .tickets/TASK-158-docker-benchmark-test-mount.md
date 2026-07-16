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

Status: In-Progress
