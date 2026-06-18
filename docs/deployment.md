# marcedit-web — production deployment

This guide is the canonical operator reference for marcedit-web on
`https://libtools2.smith.edu/marcedit-web/`. The deploy model is
native Python 3.9 + systemd + Apache + mod_shib on RHEL 8.10.
Container runtimes (Docker, Podman) are not used; see
`docs/superpowers/specs/2026-06-01-cicd-native-deploy-design.md`
for the rationale.

## Quick start (existing host)

After ITS has done the four one-time root operations (see
`docs/its-setup.md`), day-to-day deploys are:

```bash
sudo -iu marcedit
cd /var/www/html/marcedit-web
bash scripts/deploy.sh
```

That's the entire operator contract.

## Filesystem layout on libtools2

```
/var/www/html/marcedit-web/      # the repo
├── .venv/                       # python3.9 venv, owned by marcedit
├── marcedit_web/                # app code
├── data/                        # SQLite, audit, uploads (marcedit-owned)
│   ├── marcedit.db              # SQLite (WAL mode)
│   ├── marcedit.db-wal
│   ├── marcedit.db-shm
│   ├── audit/audit-YYYY-MM-DD.log
│   ├── tasks/
│   └── uploads/<user>/upload.mrc
├── .streamlit/secrets.toml      # gitignored (Google OAuth)
├── .env                         # gitignored (systemd EnvironmentFile)
└── scripts/, deploy/, docs/     # source-controlled
```

The systemd unit binds Streamlit to `127.0.0.1:8501`. Apache
reverse-proxies `/marcedit-web/` to that port. Port 8501 is
never network-reachable.

## Environment variables

`.env` is read by systemd's `EnvironmentFile=` directive. Format:
bare `KEY=VALUE` lines, no `export`, no shell expansion. See
`.env.example` for the canonical list and defaults.

The most operationally important ones:

| Var | Purpose |
| --- | --- |
| `MARCEDIT_WEB_PROD` | Set to `1` in production. Refuses anonymous sessions. |
| `MARCEDIT_WEB_ADMINS` | Comma-separated allowlist of eppns/emails that get the Tasks code view. |
| `MARCEDIT_WEB_PROXY_SECRET` | Shared secret Apache injects to prove a request came through the proxy. Without it, header identity is refused (fail-closed). Must match `/etc/httpd/marcedit-web-attestation.conf`. |
| `MARCEDIT_WEB_AUDIT_DIR` | Audit JSONL location. |
| `MARCEDIT_WEB_DB_PATH` | SQLite path. |
| `MARCEDIT_WEB_TASKS_ROOT` | Where per-user task .py files materialize. |
| `MARCEDIT_WEB_UPLOADS_ROOT` | Where signed-in users' uploads persist. |

Upload caps and Streamlit limits are also in `.env.example`.

## Trust model and identity

`marcedit_web.lib.identity.current_user()` resolves identity in
this order: `st.user.email` (Google OAuth) → `REMOTE_USER`
(Shibboleth) → `eppn` (Shibboleth) → `"anonymous"`.

On libtools2, Apache + mod_shib protects every request to
`/marcedit-web/` via the `<Location /marcedit-web>` block in
`deploy/libtools2-marcedit.conf.snippet`. mod_shib populates
`REMOTE_USER` and the `eppn` env var on authenticated requests;
Apache forwards both as HTTP headers via `RequestHeader set
… "expr=…"`, after first stripping any client-supplied versions
with `RequestHeader unset … early`.

In production mode (`MARCEDIT_WEB_PROD=1`), an anonymous result
is refused via `session.enforce_auth()` — the page never renders
and an `anonymous-action-refused` audit event is emitted.

### Proxy attestation (TASK-073)

The header scrub above only runs for traffic that passes through the
`<Location /marcedit-web>` block. Because Streamlit listens on
`127.0.0.1:8501`, any other local process on the shared host could otherwise
connect straight to `:8501`, forge `REMOTE_USER`, and gain admin (which
unlocks the raw-Python Code view → RCE as `marcedit`). To close that, the app
trusts `REMOTE_USER` / `eppn` **only** when the request also carries an
`X-MarcEdit-Proxy-Attestation` header matching `MARCEDIT_WEB_PROXY_SECRET`
(constant-time compare). Absent or invalid attestation, the header identity is
dropped to `anonymous` (fail-closed).

**Provision the secret (one value, two places):**

1. `openssl rand -hex 32`
2. Put it in the app's `.env` as `MARCEDIT_WEB_PROXY_SECRET=…`.
3. Put the *same* value in `/etc/httpd/marcedit-web-attestation.conf` (see
   `deploy/marcedit-web-attestation.conf.example`), owner `root:apache`, mode
   `0640`, installed **outside** `conf.d/` so Apache's `*.conf` autoglob does
   not set the header globally.
4. `sudo systemctl restart marcedit-web && sudo systemctl reload httpd`.

If the app shows everyone as `anonymous` after deploy, the `.env` secret and
the Apache include disagree — re-check steps 2–3. **Loopback only:** `:8501`
must never be exposed beyond loopback (the systemd unit binds `127.0.0.1`; the
compose files publish `127.0.0.1:8501:8501`).

## Google OAuth (optional)

For dev / staging or for an OAuth-only path, copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
and fill in:

- `client_id` / `client_secret` from Google Cloud Console
- `redirect_uri` = `https://libtools2.smith.edu/marcedit-web/oauth2callback`
- `cookie_secret` from `python -c 'import secrets; print(secrets.token_urlsafe(64))'`

Register the same `redirect_uri` in Google Cloud Console under the
OAuth client's "Authorized redirect URIs".

Both identity sources coexist. If a user is signed in via Google
AND a `REMOTE_USER` header is present, OAuth wins.

## Service management

The systemd unit is `marcedit-web.service`.

```bash
sudo systemctl status marcedit-web
sudo systemctl restart marcedit-web   # marcedit user can do this via NOPASSWD
sudo systemctl stop marcedit-web
journalctl -u marcedit-web -f         # follow stdout/stderr
```

The unit replicates the Dockerfile's hardening at the systemd
layer:

- `User=marcedit`, `Group=marcedit`
- `NoNewPrivileges=true`
- `ProtectSystem=strict` — filesystem is read-only by default
- `ProtectHome=true`
- `PrivateTmp=true`
- `ReadWritePaths=/var/www/html/marcedit-web/data` — only this dir
  is writable; a sandboxed task that escapes its workdir can't
  overwrite the venv or app code.

## Audit log

Two surfaces, both written for every event:

- **JSONL** — `/var/www/html/marcedit-web/data/audit/audit-YYYY-MM-DD.log`.
  One JSON object per line; tail/grep surface. Configure logrotate
  via the sample in `docs/its-setup.md`.
- **SQLite** — `audit_events` table in `marcedit.db`. Indexed on
  `(user_email, ts)` and `(kind, ts)`. Analyst query surface.

Event kinds emitted today: see the full list in the v3.2 changelog;
the most operationally relevant are `upload-accepted`/`upload-rejected`,
`task-saved`/`task-deleted`, `sandbox-timeout`/`sandbox-nonzero-exit`,
`admin-action`, and (prod mode only) `anonymous-action-refused`.

Downloads of content the cataloger already had access to upload
are not audited by design — they aren't security-relevant in this
app's threat model. Add reverse-proxy egress logging at the Apache
layer if your deployment requires it.

## Database

SQLite WAL mode at `data/marcedit.db`. Three files:
`marcedit.db`, `marcedit.db-wal`, `marcedit.db-shm`.

Backup: stop the service, copy all three files, restart. Or use
`sqlite3 marcedit.db ".backup /path/to/backup.db"` online.

Schema version tracked in the `_schema_version` table. v1 added
`audit_events` (TASK-049); v2 added `tasks` (TASK-050); v3 added
uploads (TASK-051). Migrations run on first request and are
idempotent.

## Smoke tests after deploy

1. `curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health` →
   should print `ok`.
2. `curl -I https://libtools2.smith.edu/marcedit-web/` while logged
   out → should redirect to Shibboleth.
3. After Shib login, the sidebar should show the cataloger's eppn,
   not `anonymous`.
4. `sudo systemctl show -p MainPID marcedit-web | xargs -I {} ps -o user= -p {}` →
   should report `marcedit` (not `root`, not `apache`).
5. Tail today's audit log — `tail -F /var/www/html/marcedit-web/data/audit/audit-$(date -u +%F).log` —
   then perform an upload through the UI; an `upload-accepted` event
   should appear.
6. Forged-header refusal — `curl -s -H 'REMOTE_USER: someone@smith.edu'
   http://127.0.0.1:8501/marcedit-web/` sent straight to the backend
   (bypassing Apache) must NOT yield an identified/admin session: in prod it
   is refused and the sidebar shows `anonymous`, never the forged eppn.

## Runtime temp files

The app writes large per-session working files under `/tmp` with
`marcedit-web-*` prefixes. Abrupt browser closes can leave old
directories behind. Add a conservative cleanup job:

```bash
find /tmp -maxdepth 1 -type d -name 'marcedit-web-*' -mtime +2 \
    -print -exec rm -rf {} +
```

(Run as root from a daily cron; the marcedit user can't see other
users' /tmp dirs in PrivateTmp=true mode, but root can clean them.)

## Accessibility

The app targets WCAG 2.1 AA for content the app controls. See the
accessibility section in `marcedit_web/render/*` source comments
and TASK-054 for the audited boundary.
