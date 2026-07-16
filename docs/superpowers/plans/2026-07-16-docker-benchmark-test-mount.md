# TASK-158 Docker Benchmark Test Mount Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing large-batch benchmark contract tests pass inside the development/test Compose container by mounting their one required script read-only.

**Architecture:** Preserve the production Docker image and benchmark implementation. Add one exact file bind mount to `docker-compose.yml`, pin it with the repository's existing text-based Compose contract tests, and verify the real container can load and run the script.

**Tech Stack:** Docker Compose, YAML, Python 3.9, pytest

**Ticket:** [TASK-158](../../../.tickets/TASK-158-docker-benchmark-test-mount.md)

**Design:** [Approved design](../specs/2026-07-16-docker-benchmark-test-mount-design.md)

## Global Constraints

- Mount only `./scripts/benchmark-large-batch.py`; do not mount all of `scripts/`.
- Container target is exactly `/app/scripts/benchmark-large-batch.py`.
- The mount is read-only through the `:ro` suffix.
- Do not modify the Dockerfile, `.dockerignore`, benchmark implementation, or benchmark test behavior.
- Do not replace either benchmark test with a skip.
- Preserve unrelated workspace changes and runtime data.
- Follow red-green-refactor: observe the Compose contract test fail before editing Compose.
- Mark TASK-158 `In-Progress` when its isolated worktree is created and `Completed` only after Docker verification and review pass.

## File Structure

- Modify `.tickets/TASK-158-docker-benchmark-test-mount.md`: lifecycle and exact verification evidence.
- Modify `tests/test_docker_compose_config.py`: pin the required file mount.
- Modify `docker-compose.yml`: add the single read-only bind mount.

---

### Task 1: Mount the benchmark script for Docker tests

**Files:**
- Modify: `.tickets/TASK-158-docker-benchmark-test-mount.md`
- Modify: `tests/test_docker_compose_config.py`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: host file `./scripts/benchmark-large-batch.py`
- Produces: container file `/app/scripts/benchmark-large-batch.py`
- Preserves: production image contents and existing Compose service behavior

- [ ] **Step 1: Create an isolated TASK-158 worktree and mark the ticket In-Progress**

Use `superpowers:using-git-worktrees` from commit `e37489d` or a descendant containing the approved TASK-158 design. Change the ticket's only status line to:

```markdown
Status: In-Progress
```

- [ ] **Step 2: Write the failing Compose contract test**

Add this test beside the existing environment/mount configuration tests in `tests/test_docker_compose_config.py`:

```python
def test_compose_mounts_large_batch_benchmark_read_only():
    """Docker tests need the benchmark without exposing all host scripts."""
    compose = Path("docker-compose.yml").read_text()

    assert (
        "- ./scripts/benchmark-large-batch.py:"
        "/app/scripts/benchmark-large-batch.py:ro"
    ) in compose
```

- [ ] **Step 3: Run the contract test and verify RED**

Run:

```bash
python3 -m pytest tests/test_docker_compose_config.py::test_compose_mounts_large_batch_benchmark_read_only -q
```

Expected: one failure because the exact mount is absent from `docker-compose.yml`.

- [ ] **Step 4: Add the minimum Compose mount**

Add this one entry under the service's existing `volumes` list, immediately after the tests mount:

```yaml
      - ./scripts/benchmark-large-batch.py:/app/scripts/benchmark-large-batch.py:ro
```

Do not add `scripts/` to the Dockerfile or mount the whole directory.

- [ ] **Step 5: Run the contract test and verify GREEN**

Run:

```bash
python3 -m pytest tests/test_docker_compose_config.py::test_compose_mounts_large_batch_benchmark_read_only -q
docker compose config --quiet
```

Expected: the pytest command reports `1 passed`; Compose exits 0 without configuration errors.

- [ ] **Step 6: Run the previously failing tests in Docker**

Run:

```bash
docker compose run --rm marcedit-web pytest tests/test_large_batch_benchmark.py -q
```

Expected: `2 passed` with no skips or failures.

- [ ] **Step 7: Commit Task 1**

```bash
git add .tickets/TASK-158-docker-benchmark-test-mount.md tests/test_docker_compose_config.py docker-compose.yml
git commit -m "test: mount large-batch benchmark in Docker"
```

---

### Task 2: Verify, review, and complete TASK-158

**Files:**
- Modify: `.tickets/TASK-158-docker-benchmark-test-mount.md`

**Interfaces:**
- Consumes: Task 1's Compose mount and test commit
- Produces: a clean Docker baseline for TASK-155 and a completed TASK-158 ticket

- [ ] **Step 1: Run the complete host Compose contract module**

Run:

```bash
python3 -m pytest tests/test_docker_compose_config.py -q
```

Expected: all collected tests pass. Report any skip rather than treating it as a pass.

- [ ] **Step 2: Run the complete Docker suite**

Run:

```bash
docker compose run --rm marcedit-web pytest -q
```

Expected: no failures. Record the exact passed total and each environment-conditional skip reason.

- [ ] **Step 3: Run static checks**

Run:

```bash
git diff --check e37489d..HEAD
docker compose config --quiet
```

Expected: both commands exit 0 without output.

- [ ] **Step 4: Request task and whole-branch review**

Use the subagent-driven task reviewer for Task 1, then use `superpowers:requesting-code-review` for the complete `e37489d..HEAD` diff. Review must verify the source and target paths, read-only mode, single-file scope, strict benchmark tests, and unchanged production image. Resolve every Critical or Important finding and rerun its covering tests.

- [ ] **Step 5: Complete the ticket with observed evidence**

Append an `Implementation Evidence` section reporting the actual host Compose-test total, Docker passed/skipped totals and skip reasons, Compose validation, and code-review outcome. Replace `Status: In-Progress` with `Status: Completed`; leave only one status line.

- [ ] **Step 6: Commit completion evidence**

```bash
git add .tickets/TASK-158-docker-benchmark-test-mount.md
git commit -m "docs: complete TASK-158 verification record"
```

- [ ] **Step 7: Prepare integration**

Use `superpowers:finishing-a-development-branch`. After TASK-158 is integrated into the branch that TASK-155 will use, rerun TASK-155's Docker baseline before dispatching its first implementer. Do not push unrelated local-main commits without showing the user the exact outgoing range.
