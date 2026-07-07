Title: Deploy current main (TASK-059..TASK-115) to libtools2 production

Scope:
- Push local main (129 commits ahead of origin) to github.com/sclibraries/marcedit-web.
- Server-side: pull via scripts/deploy.sh, which refreshes the venv and restarts
  the service; SQLite migrates itself to schema v8 on first request.
- Switch production auth to the current architecture: Google OAuth sign-in
  (st.login) + approval chain (access_gate, TASK-088/089). Requires a Google
  OAuth client and a filled .streamlit/secrets.toml on the server.
- New .env keys on the server: MARCEDIT_WEB_ADMIN_EMAILS (bootstrap admin),
  MARCEDIT_WEB_ALLOWED_DOMAINS (auto-approve domains). MARCEDIT_WEB_MODE is
  left unset (defaults to private). Public anonymous tier (port 8502 unit)
  deferred to a follow-up ticket.
- Pre-push hygiene verified: no secrets in outgoing commits; internal-only
  files (CLAUDE.md, AGENTS.md, docs/superpowers) remain gitignored; tickets
  are tracked by design (TASK-092).

Success Criteria:
- origin/main == local main.
- deploy.sh completes with healthcheck OK on libtools2.
- Cataloger signs in with Google; bootstrap admin (roconnell@smith.edu) lands
  approved with the admin role; WebSocket still connects (101).

Status: In-Progress
