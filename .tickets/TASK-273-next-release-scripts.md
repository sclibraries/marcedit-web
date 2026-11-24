Title: Release build, deploy and rollback scripts

Status: Todo
Size: M
Tier: major — deploy
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-273
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- Catalogers test the new app on libtools2 beside production, which must not be
  touched, and a bad release must undo itself.

Scope:
- `scripts/next/build-release.sh` (owner's machine), `scripts/next/deploy.sh`
  and `scripts/next/rollback.sh` (host), per the contract's "Deploying".

Out of scope:
- Units, Apache, watchdog (TASK-274); `scripts/deploy.sh`, `marcedit_web/ops/`.

Likely files:
- `scripts/next/*`, `tests/test_next_deploy.py`

Acceptance tests (scripts run for real in a temporary folder with stand-in
`systemctl`, `curl` and `pip`):
- A failed health check puts back the previous release and the exact earlier
  `data/`, starts it and exits non-zero. The data is a real SQLite database
  with changes still in its `-wal`: after the restore the rows are the old
  ones, and no file created after the backup remains.
- A first deploy that fails leaves the service stopped, with a clear message.
- Stops before changing anything: wrong checksum; running as root or
  `marcedit`; a root folder that is, is inside, or contains `/var/www/html`
  (symlinks followed); the same release again; another deploy or rollback
  running.
- A failed dependency install leaves the running release, its venv and
  `current` as they were.
- A backup that fails (no space) stops the deploy and starts the old release.
- `rollback.sh` refuses, before stopping the service, a backup that is missing,
  incomplete, or names a release that isn't there.
- A restore that fails leaves the service stopped and the backup in place.
- Restored files keep their owner-only permissions.
- The build refuses a dirty tree; the archive has no `.env`, `.streamlit/`,
  keys, `data/` records, tickets or `node_modules`.

Verification:
- `bash -n` on each script; host: `python3 -m pytest -ra tests/test_next_deploy.py`
- From the worktree, committed files only:
  `git archive HEAD | docker build -q -t marcedit-web:r1 -`, then
  `docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data:/app/data:ro" -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" marcedit-web:r1 pytest -ra tests/`
- Without Streamlit installed:
  `git archive HEAD | docker run --rm -i python:3.9-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w; pip install -q -r requirements-api.txt "pytest>=8,<9"; ! python -c "import streamlit" 2>/dev/null; python -m pytest -q tests/api'`

Plan:
1. Build script and archive contents test.
2. Deploy: lock, checks, unpack, backup, switch, health.
3. Restore, shared by deploy and rollback.

Handoff:
-

Review:
-
