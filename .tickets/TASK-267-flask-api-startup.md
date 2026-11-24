Title: Flask API: configuration, startup and health

Status: Completed
Size: M
Tier: major — new dependencies
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-267
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- The React app needs an API that runs without Streamlit and refuses to start
  half-configured or pointed at another service's data.

Scope:
- `requirements-api.txt`: Flask>=3.1,<3.2, waitress==3.0.2,
  pymarc>=5.1.2,<6, jsonschema>=4.23,<5. The Dockerfile installs it too (test
  image only), so `THIRD_PARTY_NOTICES.md` and its test cover both files.
  `requirements.txt` doesn't change. CI: the existing job installs
  both files; a new job installs this one and pytest and runs `tests/api`.
- `marcedit_web/api/`: `create_app()`, configuration, startup, error answers,
  response headers, `GET /api/v1/health`, `python -m marcedit_web.api`
  (waitress on 127.0.0.1, port and url_prefix from configuration).
- ARCHITECTURE.md: the API layer (`api → lib`, never the reverse), marked as
  not in production yet.

Out of scope:
- Identity, other routes, frontend, deploy files, database changes, `lib/db.py`,
  `views/`, `render/`, `App.py`.

Likely files:
- `marcedit_web/api/*.py`, `requirements-api.txt`, `Dockerfile`,
  `.github/workflows/test.yml`, `tests/api/`, `ARCHITECTURE.md`,
  `THIRD_PARTY_NOTICES.md`, `tests/test_product_identity.py`

Acceptance tests:
- Every row of the contract's configuration table refuses to start when broken
  (one parametrized test), including a storage setting or symlink that leads
  outside the data root: the second service must not open production's files.
- Starting on a database with a newer schema refuses and leaves its version and
  contents as they were; `db.init_schema()` would set the version back.
- `/health` gives 503 and creates or migrates nothing when the database is
  missing or at another schema version.
- Through a real waitress server with the url_prefix, `/health` answers under
  the prefix.
- An unexpected error gives the plain error answer: no trace, no path.
- Importing, starting and answering never try to import Streamlit (port the
  prototype's import guard: a missing package alone wouldn't show an attempt
  that was swallowed).

Verification:
- From the worktree, committed files only:
  `git archive HEAD | docker build -q -t marcedit-web:r1 -`, then
  `docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data:/app/data:ro" -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" marcedit-web:r1 pytest -ra tests/`
- Without Streamlit installed:
  `git archive HEAD | docker run --rm -i python:3.9-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w; pip install -q -r requirements-api.txt "pytest>=8,<9"; ! python -c "import streamlit" 2>/dev/null; python -m pytest -q tests/api'`
- Host: `python3 -m pytest tests/test_deploy_units.py tests/test_docker_compose_config.py`

Plan:
1. Configuration and its table test.
2. Startup order: checks, schema version, `init_schema()`.
3. Error answers, headers, `/health`, the waitress entry point.
4. CI, Dockerfile, ARCHITECTURE.md.

Handoff:
- Head 7fe1ab6, merged into main (owner OK 2026-11-24). Image suite 2,801 passed, 35 skipped (files not in the test
  image); API without Streamlit 29 passed; host deploy tests 45 passed.

Review:
- One fix round: the API tests left storage settings in the environment for later tests.
- To TASK-268: log unexpected errors; `MARCEDIT_WEB_DEV_USER` becomes the email.
