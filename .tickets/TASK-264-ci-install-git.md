Title: Install git in CI's python:3.9-slim job

Status: In-Progress
Size: S
Tier: small — CI configuration only; no application behavior changes
Milestone: M3 — Code health
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-264

Why:
- Follow-up to TASK-263 (owner, 2026-11-16). CI now runs in python:3.9-slim, but
  `tests/test_task_194_runtime.py::test_runtime_job_artifacts_do_not_dirty_a_deployment_checkout`
  runs `git init`, and the image has no git, so CI stays red on that one test.

Scope:
- `.github/workflows/test.yml`: before "Install dependencies", install git in the
  container (`apt-get update && apt-get install -y --no-install-recommends git`). Nothing else.

Out of scope:
- Any test, application code, dependency or other workflow setting.

Likely files:
- .github/workflows/test.yml

Acceptance tests:
- The workflow's steps, run in python:3.9-slim with the git install added, report
  0 failed, so CI goes green.

Verification:
- From the worktree:
  `docker run --rm -v "$WT":/src:ro python:3.9-slim sh -c 'apt-get update -qq && apt-get install -y -qq --no-install-recommends git >/dev/null && cp -r /src /w && cd /w && pip install -q --upgrade pip && pip install -q -r requirements.txt && pip install -q -e . --no-deps && python -m pytest -q -ra'`
  and report the pass/fail/skip counts.

Handoff:
- (orchestrator fills in after the check)

Review:
- (orchestrator fills in)
