# TASK-073 — Require proxy attestation before trusting identity headers

**Status:** Completed — merged to local main (commit SHAs rewritten by TASK-087); push no longer blocked
**Priority:** Tier 0 — Security (urgent); collaboration foundation
**Worktree:** `.claude/worktrees/task-073-proxy-attestation` (branch `worktree-task-073-proxy-attestation`)
**Plan:** `docs/superpowers/plans/2026-06-18-proxy-attestation.md`
**Source:** Deep code audit 2026-06-17 — finding S2 (HIGH, confirmed)

## Title

Don't trust `REMOTE_USER`/`eppn` unless the request is attested to have arrived
through the trusted Apache/Shibboleth proxy.

## Scope

- `identity.current_user()` (`lib/identity.py:76-82`) returns the header value
  verbatim; `task_admin.is_admin()` is a plain `user in admins` test. The only
  forgery defense is an Apache header scrub that runs solely for proxied
  traffic. On the shared host, a loopback-capable actor can hit `127.0.0.1:8501`
  directly, forge `REMOTE_USER: <admin>`, unlock the raw-Python Code view, and
  achieve RCE as `marcedit`.
- Have Apache inject a shared-secret attestation header (or use a UNIX socket /
  dedicated token); reject `REMOTE_USER`/`eppn` in the app when attestation is
  absent.
- Ensure loopback-only binding everywhere (systemd already does; fix
  `docker-compose.pull.yml` to prefix `127.0.0.1:`). Document that 8501 must
  never be reachable by untrusted local apps.
- Route all identity reads through `identity.current_user()` so the check is
  single-point (coordinated with TASK-078).
- Foundation note: correct attributed identity is a prerequisite for
  collaboration provenance (TASK-082) and record locking (TASK-086).

## Success Criteria

1. A request sent to the upstream without the attestation header is treated as
   unauthenticated (no identity, no admin) even if it sets `REMOTE_USER`.
2. Legitimate Apache+Shib traffic still resolves identity and admin.
3. `preflight-check.sh` / deploy docs assert loopback binding + the attestation
   secret.
4. Tests cover forged-header rejection; focused tests and the Docker test suite
   pass before completion.

## Implementation Progress (2026-06-18)

Implemented on branch `worktree-task-073-proxy-attestation` (8 commits,
9c2de64..ac58567). All 8 plan tasks' code/docs are done:

- `identity.current_user()` gates `REMOTE_USER`/`eppn` on a constant-time
  `X-MarcEdit-Proxy-Attestation` match against `MARCEDIT_WEB_PROXY_SECRET`,
  fail-closed; OAuth path untouched. Single enforcement point (no TASK-078
  refactor). Contract docstring added.
- Tests: forged/wrong-length/fail-closed/OAuth-unaffected matrix + transitive
  admin denial + prod `enforce_auth` refusal.
- Loopback-bound both compose files + secret passthrough; `.env.example`,
  Apache 0640-include (`deploy/marcedit-web-attestation.conf.example`),
  preflight assertion, deployment.md + its-setup.md.

**Verification status:**
- Focused suite (identity, session_enforce, task_admin): **53 passed** locally.
- Full local suite: **676 passed**; only failures are pre-existing macOS
  sandbox-primitive incompatibilities in `test_sandbox.py` (confirmed
  identical on untouched `main`) + 1 `streamlit_ace`-missing collection error.
  Zero new failures from this work.
- Authoritative pinned-Python-3.9 Docker suite
  (`docker compose run --rm marcedit-web pytest -q`): **720 passed, 2 skipped**
  (post-review; the 2 skips are build-config tests that no-op inside the
  runtime image). Criterion 4 satisfied.

### Code review (2026-06-18)

Senior-reviewer subagent over `ab27c7e..ac58567`. Found a **Critical** bug:
`current_user()` read `REMOTE_USER`/`eppn`/`X-MarcEdit-Proxy-Attestation` with
exact-case lookups, but prod resolves headers via `dict(st.context.headers)`,
which Streamlit normalizes to Http-Header-Case — so every lookup returned
`None`, failing the gate closed and locking out all Shibboleth catalogers
(criterion 2). Verified against Streamlit 1.57.0. (The `REMOTE_USER`/`eppn`
casing bug predated TASK-073 — TASK-047 — but was latent because the native
Shib prod path isn't live yet.)

Fix (commit `080aa1f`): case-insensitive `_header()` lookup used by
`current_user()` + `_attestation_ok()`; bytes compare (non-ASCII safety);
regression tests through the **real** `StreamlitHeaders`; corrected preflight
message. All review findings (1 Critical, 2 Important, 1 Minor; 1 false alarm)
resolved. Re-verified: focused 56 passed, Docker **720 passed**.

Branch `worktree-task-073-proxy-attestation` (`9c2de64..080aa1f`, 8 commits)
is ready to merge.
