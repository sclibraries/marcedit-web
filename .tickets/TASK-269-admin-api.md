Title: Admin API

Status: Todo
Size: M
Tier: major — who may use the app
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-269
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- Admins approve people, set roles and manage allowed domains (parity row 2).

Scope:
- `GET /api/v1/admin/access` and POST `users/approve`, `users/revoke`,
  `users/role`, `domains/add`, `domains/remove`, per the contract, including
  `from_settings`. POSTs answer with the same shape as the GET.
- A lib function for approving an existing person; `approve_user` and its
  callers don't change.
- Admin audit events record who acted (`actor`) as well as who was changed;
  existing fields keep their meaning.

Out of scope:
- Frontend; the Streamlit Admin page.

Likely files:
- `marcedit_web/api/admin.py`, `marcedit_web/schemas/api/*.json`,
  `marcedit_web/lib/authz.py`, `tests/api/test_admin.py`,
  `tests/test_authz_admin.py`

Acceptance tests:
- A non-admin gets 403 on every admin route and no admin change is made (one
  parametrized test over all routes); their own first-visit row and the refusal
  audit are expected.
- Approve, revoke and role change take effect on that person's next request.
- Approving someone who is already approved, or was just made admin by another
  request, changes neither role nor approval record.
- Each change sent twice leaves the same result as once.
- An unknown email is 404 and creates no one; a malformed email or domain is
  400 and writes nothing.
- Revoking or demoting an admin, or removing a domain, that comes from the
  settings is 409: the next start would silently undo it.
- Removing a domain affects only new accounts.
- Audit rows name actor and target.

Verification:
- From the worktree, committed files only:
  `git archive HEAD | docker build -q -t marcedit-web:r1 -`, then
  `docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data:/app/data:ro" -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" marcedit-web:r1 pytest -ra tests/`
- Without Streamlit installed:
  `git archive HEAD | docker run --rm -i python:3.9-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w; pip install -q -r requirements-api.txt "pytest>=8,<9"; ! python -c "import streamlit" 2>/dev/null; python -m pytest -q tests/api'`

Plan:
1. Lib: approve-existing, audit actor, settings lookup.
2. Routes and schemas.
3. Parametrized access test.

Handoff:
-

Review:
-
