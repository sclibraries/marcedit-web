Title: Run CI's Python 3.9 tests in a python:3.9-slim container

Status: Completed
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
- Head 298f896 (one fix round), merged into main (owner OK 2026-11-16). Workflow steps in python:3.9-slim: 2794 passed, 5 skipped, 1 failed (git missing in the image). Private handoffs: TASK-263.md, TASK-263-fr1.md.

Review:
- Container and `python -m pytest` met. One test needs a `git` executable; at the fix-round limit the owner chose merge now, with git installed in TASK-264.
