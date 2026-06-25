# TASK-047 — Google OAuth via Streamlit native auth

**Status:** Completed
**Stage:** First stage of user-identity work.

## Title

Local-dev and early-rollout deployments need a real-identity story
before Shibboleth lands. Add Google OAuth via Streamlit 1.42+'s
``st.login`` / ``st.user``. The OAuth flow + state/PKCE/CSRF +
session cookie are handled by Streamlit itself; the app's job is
to read ``st.user.email`` when present and fold it into the
existing identity contract.

## Scope

- **`.streamlit/secrets.toml.example`** (committed) — template
  showing the required ``[auth]`` + ``[auth.google]`` keys with
  placeholder values + setup notes for ops.
- **`.streamlit/secrets.toml`** (gitignored) — operator fills this
  in with real Google OAuth client + cookie secret. Already covered
  by the existing ``.gitignore`` pattern; verify.
- **`marcedit_web/lib/identity.py`**:
  * New ``oauth_user() -> str | None`` helper that defensively reads
    ``st.user.email`` when ``st.user.is_logged_in`` is True. Returns
    None outside Streamlit / when not logged in / on any access
    error (Streamlit's API surfaces have moved between versions).
  * ``current_user(headers=None)`` priority becomes:
    1. ``st.user.email`` (OAuth) when logged in
    2. ``REMOTE_USER`` HTTP header (Shibboleth)
    3. ``eppn`` HTTP header (Shibboleth fallback)
    4. ``ANONYMOUS`` sentinel
  * ``is_oauth_configured()`` — True when ``[auth]`` is present in
    ``st.secrets``. Drives the sidebar UI's render decision.
- **`marcedit_web/App.py`** entrypoint:
  * Renders a sign-in / sign-out block in the sidebar BEFORE the
    page navigation, so it appears on every page consistently.
  * Anonymous + OAuth configured → "Sign in with Google" button.
  * Logged in → "Signed in as alice@example.com" + "Sign out" button.
  * Not configured (no secrets.toml or no [auth] section) → no
    sign-in UI; anonymous flow continues exactly as today.
- **`enforce_auth()` unchanged** — it already calls
  ``is_anonymous(current_user())`` which now sees OAuth identities.
  Prod mode keeps blocking anonymous regardless of source.
- **Audit** — already routes through ``current_user()``; OAuth
  emails will appear in audit rows automatically.
- **Tests** (`tests/test_identity.py`):
  * ``current_user`` prefers ``st.user.email`` when logged in.
  * ``current_user`` falls back to ``REMOTE_USER`` when not logged in.
  * ``current_user`` falls back to ``ANONYMOUS`` when neither set.
  * ``oauth_user`` defensive: returns None when ``st.user`` access
    raises (covers older Streamlit / runtime-not-ready cases).
  * ``is_oauth_configured`` returns True when ``[auth]`` is in
    secrets, False otherwise.
- **`docs/deployment.md`** — new "Google OAuth (dev / staging)"
  section explaining secrets.toml setup, Google Cloud Console
  steps, and how the multi-source identity rule works.

## Out of scope (with reasons)

- **SQL backend for user accounts.** Streamlit native auth doesn't
  need one. Adding it now commits to a schema we haven't validated
  against real needs. Worth doing when we add per-user persistent
  workspaces / preferences.
- **Multi-provider login UI.** Google only for now. Adding
  Microsoft / Okta / GitHub is data-only once the plumbing exists.
- **Self-serve account management, password reset, profile pages.**
  OAuth means Google handles all of that.
- **Database-backed admin list.** ``MARCEDIT_WEB_ADMINS`` env-var
  stays. Operators put Google emails in it the same way they put
  Shibboleth eppns today.
- **CSRF / state / PKCE hardening beyond defaults.** Streamlit's
  native flow handles these. We rely on its implementation.

## Success Criteria

1. With ``[auth.google]`` configured in ``secrets.toml`` and a real
   Google OAuth client, clicking "Sign in with Google" completes the
   OIDC flow and the sidebar shows "Signed in as <email>".
2. ``current_user()`` returns the OAuth email post-login; audit rows
   carry it.
3. With ``MARCEDIT_WEB_PROD=1`` and no sign-in, every page renders
   the existing login-needed banner (the prod gate still works).
4. With ``MARCEDIT_WEB_PROD`` unset and ``[auth]`` not configured,
   the app behaves exactly as today (anonymous browsing in dev).
5. ``MARCEDIT_WEB_ADMINS`` containing the signed-in email grants the
   Code-view in the Tasks editor.
6. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
# After secrets.toml setup, smoke-test the OAuth flow in a browser.
```
