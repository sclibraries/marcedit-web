Title: API request identity and access rules

Status: Completed
Size: M
Tier: major — auth
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-268
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- The API must know who is calling without trusting anything a browser sends.

Scope:
- `identity.proxy_user(headers)`: lowercased `X-MarcEdit-User`, only with a
  valid attestation. `current_user` behaves as before.
- Access checks for every `/api/v1` route except `/health`, the Origin and
  `X-MarcEdit-Request` checks, `GET /api/v1/me`.
- `MARCEDIT_WEB_DEV_USER` holds the email to act as (TASK-267 made it 1 or 0).
- An unexpected error is written to the service log with its traceback; the
  answer stays plain (TASK-267 left nothing in the log).
- `authz.authorize`: the first-visit insert tolerates another request having
  inserted the row, and returns that row's decision (port the prototype's).
- Schemas for `/me` and the error answer; request-body checking.

Out of scope:
- Admin routes, frontend.

Likely files:
- `marcedit_web/api/access.py`, `marcedit_web/api/me.py`,
  `marcedit_web/schemas/api/*.json`, `marcedit_web/lib/identity.py`,
  `marcedit_web/lib/authz.py`, `tests/api/`, `tests/test_authz.py`

Acceptance tests:
- Every cell of the contract's access table, on a stand-in route that changes
  data (one parametrized test): missing, wrong and valid attestation; approved,
  pending, revoked, admin. Refusals are audited.
- A revoke or role change applies to the person's next request.
- A `REMOTE_USER` or `eppn` header, a cookie or a body field never changes who
  the caller is.
- Opened as A, now signed in as B: a change is 409 and nothing is written.
- Without the exact Origin or the request header, a change is refused before
  its body is read.
- Through a real waitress server, `X-MarcEdit-User` arrives and
  `X_MarcEdit_User` doesn't (waitress drops underscore headers, which a Flask
  test client wouldn't show).
- Two first requests at once for one person both succeed, with one row and one
  provisioning audit event (threads, real database file); a person revoked
  between lookup and insert stays revoked.
- A development identity acts as its email, and one that isn't an email
  address refuses to start.
- An unexpected error's traceback is in the log and not in the answer.
- Streamlit's own sign-in behaves as before (existing identity and authz tests,
  unchanged).

Verification:
- From the worktree, committed files only:
  `git archive HEAD | docker build -q -t marcedit-web:r1 -`, then
  `docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data:/app/data:ro" -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" marcedit-web:r1 pytest -ra tests/`
- Without Streamlit installed:
  `git archive HEAD | docker run --rm -i python:3.9-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w; pip install -q -r requirements-api.txt "pytest>=8,<9"; ! python -c "import streamlit" 2>/dev/null; python -m pytest -q tests/api'`

Plan:
1. `proxy_user` and the authz insert.
2. Access checks and their table test.
3. Change checks (Origin, request header).
4. `/me`, schemas.

Handoff:
- Head 35d1d51, merged into main (owner OK 2026-11-24). Image suite 2,824 passed, 35 skipped (files not in the test
  image); API without Streamlit 52 passed.

Review:
- No fix round. Twenty raw requests to a real server without a valid identity reached no route; each of eight rules,
  disabled in turn, fails a test.
- To TASK-269: request-body checking (no route here has a body) and dropping `version` from `/me`.
