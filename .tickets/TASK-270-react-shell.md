Title: React shell, served by Flask

Status: Todo
Size: M
Tier: major — new dependencies
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-270
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- Gives every later screen one place to live: build, types, tests, layout.

Scope:
- `frontend/`: React, TypeScript, Vite, Tailwind, shadcn/ui, React Router,
  Vitest with Testing Library, json-schema-to-typescript. Exact versions in
  `package.json` and the lockfile. Node 24. Add a shadcn component only where a
  screen uses it.
- TypeScript types generated from `marcedit_web/schemas/api/`;
  `npm run types:check` fails if they are stale.
- Shell: narrow sidebar, product name, a Home page with one line of text, the
  signed-in email. Only links that work are shown.
- Flask serves the build from a configured folder, per the contract.
- CI job. `frontend/README.md`: running it locally with
  `MARCEDIT_WEB_DEV_USER`.

Out of scope:
- Session expiry, Admin page, jobs, dark mode.

Likely files:
- `frontend/**`, `marcedit_web/api/static.py`, `.github/workflows/test.yml`,
  `.gitignore`, `tests/api/test_static.py`

Acceptance tests:
- Under `/marcedit-next/`, assets load and a deep link (`/marcedit-next/admin`)
  returns the app; an unknown `/api/v1` path is a 404 error answer, not
  `index.html`.
- A path outside the build folder (`../`, encoded too) is never served.
- The built `index.html` has no inline script, so the CSP doesn't block it.
- Changing a schema without regenerating types fails `types:check`.
- The orchestrator opens the built page in a browser: no console errors,
  keyboard focus visible, usable at 1280 px.

Verification:
- `git archive HEAD frontend marcedit_web/schemas/api | docker run --rm -i node:24-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w/frontend; npm ci; npm run typecheck; npm run types:check; npm test; npm run build'`
- From the worktree, committed files only:
  `git archive HEAD | docker build -q -t marcedit-web:r1 -`, then
  `docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data:/app/data:ro" -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" marcedit-web:r1 pytest -ra tests/`
- Without Streamlit installed:
  `git archive HEAD | docker run --rm -i python:3.9-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w; pip install -q -r requirements-api.txt "pytest>=8,<9"; ! python -c "import streamlit" 2>/dev/null; python -m pytest -q tests/api'`

Plan:
1. Toolchain, scripts, lockfile.
2. Types from schemas, drift check.
3. Shell.
4. Flask static serving.
5. CI, README.

Handoff:
-

Review:
-
