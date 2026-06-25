# TASK-021 — Prod auth gate, non-root container, deployment docs

**Status:** Completed
**Stage:** 21 (per `the-goal-of-this-sequential-sifakis.md` v3)

## Title

Add a production-mode auth gate (`MARCEDIT_WEB_PROD`) so the live
deployment refuses anonymous sessions with a friendly login-needed
page + audited refusal. Harden the container so it runs as an
unprivileged user. Ship the nginx/Shibboleth deployment guide that
ops has been asking for.

## Scope

- `marcedit_web/lib/identity.py`:
  * Add `is_prod()` — truthy when `MARCEDIT_WEB_PROD` is set to
    `1`/`true`/`yes` (case-insensitive).
  * Add `is_anonymous(user)` — convenience wrapper around the
    sentinel.
- `marcedit_web/lib/session.py`:
  * Add `enforce_auth()` — when prod+anonymous, render the friendly
    login-needed banner, emit `anonymous-action-refused` audit
    event, and call `st.stop()`. Returns silently otherwise.
  * Hooked into every page top via `init_page()` (new) that wraps
    `init() + enforce_auth()`.
- All pages (`marcedit_web/Home.py` + `marcedit_web/pages/*.py`)
  call `session.init_page()` instead of `session.init()`.
- `Dockerfile`:
  * Create non-root `marcedit` user + group; `chown` `/app` to that
    user; `USER marcedit` directive before the CMD.
  * Keep the healthcheck working.
- `docs/deployment.md`:
  * nginx-with-mod_shib reverse-proxy example, including the
    `REMOTE_USER` + `eppn` header propagation.
  * `MARCEDIT_WEB_PROD=1` callout.
  * `MARCEDIT_WEB_ADMINS` admin-allowlist callout.
  * Audit-log location reminder.
- `tests/test_identity.py`:
  * `is_prod()` parses env var correctly.
  * `is_anonymous("anonymous")` is True, named user False.
- `tests/test_session_enforce.py`:
  * `enforce_auth` exits prod-anonymous (verified by audit log
    side-effect + by patched `st.stop`).
  * `enforce_auth` no-ops in dev mode.

## Out of scope

- Streamlit-native authentication. We rely on the reverse proxy
  (Shibboleth) for actual identity assertion.
- Per-route authorization. Anonymous = denied everything in prod;
  authenticated = allowed (modulo admin-only Code view from
  Stage 17).
- A separate dev-mode "force prod" mode toggle in the sidebar.
  Ops controls this via env var.

## Success Criteria

1. `MARCEDIT_WEB_PROD=1` + no `REMOTE_USER` header → every page
   shows the login-needed banner and stops rendering.
2. Same env, with a `REMOTE_USER` header → pages render normally.
3. Unset env (dev mode) + no header → page renders, anonymous user
   shown as "anonymous" (unchanged v3 behavior).
4. Container `docker compose run --rm marcedit-web id` returns a
   non-root UID/GID.
5. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_identity.py tests/test_session_enforce.py
docker compose run --rm marcedit-web pytest -q
docker compose build && docker compose run --rm marcedit-web id
```
