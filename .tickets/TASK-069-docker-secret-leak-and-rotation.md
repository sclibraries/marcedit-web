# TASK-069 — Stop baking secrets into the image; rotate exposed secrets

**Status:** Completed (re-scoped — preventive only; rotation N/A, no leak)
**Priority:** Tier 0 — Security (urgent)
**Source:** Deep code audit 2026-06-17 — finding S1 (HIGH, confirmed)
**Branch:** task-069-docker-secrets (worktree .worktrees/task-069-docker-secrets)

## Re-scope (2026-06-17)

Rotation DROPPED — no leak occurred. Verified: `.streamlit/secrets.toml` was
NEVER committed to git history (only `config.toml` + `secrets.toml.example` are
tracked; the file is gitignored), and the owner confirms no Docker image has
ever been published to a registry. The audit's "treat as compromised, rotate"
was conditional on a publish that never happened, so the live secrets remain
confidential and do NOT need rotation. Scope is now purely PREVENTIVE: ensure
secrets can never be baked into a future image (so they stay safe once the app
is eventually published / `docker-compose.pull.yml` is used). Success criterion
#3 (rotation) is N/A; criteria #1/#2/#4 stand.

## Title

Remove the developer's real `.streamlit/secrets.toml` from the Docker image and
rotate the OAuth/cookie secrets that were exposed in a buildable context.

## Scope

- Add `.streamlit/secrets.toml` (and any `*.env` / secret `*.toml`) to
  `.dockerignore`. Note: `.gitignore` does NOT protect Docker `COPY`.
- Change `Dockerfile`'s `COPY .streamlit ./.streamlit` to copy only non-secret
  config (`COPY .streamlit/config.toml ./.streamlit/config.toml`). Provide
  secrets at runtime via a mounted file or env, never via `COPY`.
- Rotate the Google OAuth `client_secret` and the Streamlit `cookie_secret`
  (treat as compromised — they were on disk in a buildable tree and
  `docker-compose.pull.yml` implies published images). Invalidate the old
  OAuth client secret in the Google console.
- Audit that no other secret-bearing file is `COPY`'d into the image.

## Success Criteria

1. A built image contains no `secrets.toml` layer (verify via `docker history`
   / layer extraction).
2. The app authenticates with secrets supplied at runtime (mount/env), not
   baked into the image.
3. New `cookie_secret` and OAuth `client_secret` are in use; the prior values
   are invalidated upstream.
4. `.dockerignore` excludes secrets and the runtime-secret procedure is
   documented in the deploy notes.

## Resolution (2026-06-17)

Preventive fix only (rotation N/A — no leak; see Re-scope). Changes:
- `Dockerfile`: `COPY .streamlit ./.streamlit` → `COPY .streamlit/config.toml
  ./.streamlit/config.toml` (only non-secret config enters the image).
- `.dockerignore`: exclude `.streamlit/secrets.toml`, `.streamlit/secrets*.toml`,
  `.env` (defense-in-depth; `secrets.toml.example` is preserved).
- `docker-compose.pull.yml`: comment documenting that OAuth secrets must be
  supplied at runtime (env_file / secrets mount) for the published-image flow.
- `tests/test_docker_compose_config.py`: two regression guards (dockerignore
  excludes secrets; Dockerfile copies only config.toml). They run on host + CI
  (which check out the repo) and skip inside the runtime container, where the
  build files aren't mounted.

Verified: rebuilt the image and inspected it directly (bypassing the compose
mount) — `/app/.streamlit/` contains only `config.toml`; a whole-image `find`
shows no `secrets.toml` anywhere. App degrades gracefully when secrets are
absent (identity.py wraps `st.secrets` in try/except; App.py gates `st.login` on
`is_oauth_configured()`), so a secrets-free pulled image does not crash — it
falls back to "OAuth not configured" (the Shibboleth prod path needs no OAuth).
Full Docker suite: 701 passed, 2 skipped (the build-config guards, in-container).
Independent review: approve-with-nits; nits applied (pull-compose runtime-secret
comment, exact-match Dockerfile assertion). The dev `docker-compose.yml` still
bind-mounts `./.streamlit` so local runs are unaffected.

Note (out of scope): `docker-compose.pull.yml` also omits `GEMINI_API_KEY`
(present in the dev compose) — a separate pre-existing gap if the published-image
flow is meant to support the AI features.
