Title: Run CI's Python 3.9 tests in a python:3.9-slim container

Status: In-Review
Size: S
Tier: small — CI configuration only; no application behavior changes
Milestone: M3 — Code health
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-263

Why:
- CI has failed on every push since at least 2026-10-06 (last success
  2026-07-22): GitHub's ubuntu-latest no longer provides Python 3.9 through
  `actions/setup-python` ("The version '3.9' with architecture 'x64' was not
  found for Ubuntu 26.04"). A permanently red CI hides real failures, and
  production runs Python 3.9.

Scope:
- `.github/workflows/test.yml`: run the `pytest` job in the `python:3.9-slim`
  container instead of using `actions/setup-python`. Keep the install steps
  (`requirements.txt`, `pip install -e . --no-deps`) and `pytest -ra`. Add only
  what the slim image needs for the existing install to succeed (for example
  `git` if a requirement needs it), nothing else.

Out of scope:
- Any test, application code, dependency or other workflow.

Likely files:
- .github/workflows/test.yml

Acceptance tests:
- The workflow's job uses `container: python:3.9-slim` and no
  `actions/setup-python` step, so CI runs on the same Python as production.
- The workflow's install and test commands, run inside a `python:3.9-slim`
  container against the worktree, install cleanly and the suite reports
  0 failed (the deploy-file tests may skip in the container, as they already do
  in the dev image), so the first CI run after merge goes green.

Verification:
- Run the workflow's steps in `python:3.9-slim` from the worktree:
  `docker run --rm -v "$WT":/src:ro python:3.9-slim sh -c 'cp -r /src /w && cd /w && pip install -q --upgrade pip && pip install -q -r requirements.txt && pip install -q -e . --no-deps && pytest -q -ra'`
  and report the pass/fail/skip counts.

Handoff:
- (orchestrator fills in after the check)

Review:
- (orchestrator fills in)
