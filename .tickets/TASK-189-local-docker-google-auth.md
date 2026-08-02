Title: Require Google authentication for local private Docker review

Scope:
- Configure the isolated local Docker-review tree to use the existing ignored
  Google OAuth secrets for `http://localhost:8501`.
- Document that private Docker UI review always requires authentication and
  must not be performed through an anonymous bypass.
- Keep OAuth credentials ignored and out of Git.

Success Criteria:
- The worktree has an ignored `.streamlit/secrets.toml` whose redirect URI is
  `http://localhost:8501/oauth2callback`.
- The private Docker application exposes the Google sign-in control on port
  8501.
- Repository documentation explicitly states the authentication requirement
  for future private Docker UI review.
- No credential value is committed or printed in verification output.

Status: Completed

Completion Evidence (2026-08-02):
- Installed the existing local OAuth file into the isolated worktree as the
  ignored `.streamlit/secrets.toml`; `cmp` confirms the copy and
  `git check-ignore` confirms it cannot be committed normally.
- Restarted `marcedit-web`; Docker reports the service healthy and
  `/_stcore/health` returns `ok`.
- Runtime verification inside the container reports `auth_configured=True`
  and the callback `http://localhost:8501/oauth2callback` without printing any
  credential value.
- `tests/test_product_identity.py`: `14 passed`.
- Browser automation was unavailable in this session, so the control itself
  was not clicked; its render condition is satisfied by the verified runtime
  `[auth]` configuration.
