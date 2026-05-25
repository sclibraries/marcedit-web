# marcedit-web — production deployment

This guide covers the production setup ops needs to run marcedit-web
behind nginx + Shibboleth on the RedHat 9 host. Dev defaults are
permissive (anonymous sessions allowed, audit log under `data/`); this
document captures the env-var flips and reverse-proxy rules that turn
that off.

## Environment variables

| Var | Default | Purpose |
| --- | --- | --- |
| `MARCEDIT_WEB_PROD` | unset | When `1`/`true`/`yes`, the app refuses anonymous sessions: every page shows the login-needed banner and emits an `anonymous-action-refused` audit event. Leave unset for dev. |
| `MARCEDIT_WEB_ADMINS` | unset | Comma-separated allowlist of eppns / `REMOTE_USER` values that get the **Code view** in the Tasks editor. Anyone not listed sees only the form-builder. The wildcard `*` grants admin to everyone (dev escape hatch — never set in prod). |
| `MARCEDIT_WEB_AUDIT_DIR` | `data/audit` | Where the JSONL audit log is written. Make sure the mounted host directory is writable by uid `10001`. |
| `MARCEDIT_WEB_MAX_UPLOAD_BYTES` | `2147483648` (2 GB) | Batch upload cap (per file, MARC `.mrc`). Files are streamed to a per-session temp dir; lazy-read on demand. Matches the Diff per-file cap and the Streamlit framework cap. |
| `MARCEDIT_WEB_MAX_DIFF_BYTES` | `2147483648` (2 GB) | Diff-page **per-file** cap. Each uploaded file streams to a per-session temp dir and is mmap'd on use, so multi-GB total uploads no longer pin Python memory and there's no per-side aggregate cap. |
| `MARCEDIT_WEB_MAX_TASKSFILE_BYTES` | `1048576` (1 MB) | Tasksfile import cap (text). |
| `MARCEDIT_WEB_MAX_SESSION_BYTES` | `4294967296` (4 GB) | Aggregate per-session upload cap. Protects shared container disk against a single session accumulating many large batches. |
| `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` | 2048 (set in `docker-compose.yml`) | Streamlit's framework-level cap, in MB. Per-feature caps above this are the actually-enforced limits. |

## Trust model

Identity is asserted by Shibboleth at the nginx layer, not by the app:

1. Shibboleth's SP module on nginx negotiates the federated login.
2. On success, nginx writes `REMOTE_USER` (and optionally `eppn`)
   into the upstream request headers.
3. `marcedit_web.lib.identity.current_user()` reads those headers
   from `st.context.headers` and returns the identifier.
4. In prod mode, an empty `REMOTE_USER` is refused via
   `session.enforce_auth()` — the page never renders.

The app does **not** terminate Shibboleth itself and never re-verifies
the signature. Trust the reverse proxy or stop here.

## nginx + mod_shib example

```nginx
# /etc/nginx/conf.d/marcedit-web.conf

upstream marcedit_web {
    server 127.0.0.1:8501;
}

server {
    listen 443 ssl http2;
    server_name marcedit-web.example.edu;

    ssl_certificate     /etc/pki/tls/certs/marcedit-web.crt;
    ssl_certificate_key /etc/pki/tls/private/marcedit-web.key;

    # Shibboleth SP — mod_shib needs to handle these directly.
    include shib_clear_headers;
    location /Shibboleth.sso/ {
        proxy_pass http://localhost:8080;  # mod_shib backend
    }

    location / {
        # Require authentication on every request reaching the app.
        shib_request /shibauthorizer;
        shib_request_use_headers on;

        # Forward identity to Streamlit.
        proxy_set_header REMOTE_USER $remote_user;
        proxy_set_header eppn        $http_eppn;

        # Standard reverse-proxy headers Streamlit expects.
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";  # Streamlit websocket

        proxy_pass http://marcedit_web;
    }
}
```

Notes:

* `shib_request /shibauthorizer` + `shib_request_use_headers on` is
  the contract that lands `REMOTE_USER` on each upstream request.
  Without it the app gets nothing and (in prod mode) refuses every
  request.
* Streamlit needs `proxy_http_version 1.1` plus the `Upgrade` /
  `Connection: upgrade` headers — its websocket dies otherwise.
* The `shib_clear_headers` include strips client-supplied
  `REMOTE_USER` so a malicious caller can't forge identity.

## Container hardening

The image now runs as `marcedit` (uid/gid `10001`, system account, no
home, no login shell). Bind mounts in `docker-compose.yml` must allow
that uid to write:

```bash
# On the host:
sudo install -d -o 10001 -g 10001 /var/lib/marcedit-web/data
sudo install -d -o 10001 -g 10001 /var/lib/marcedit-web/data/audit
sudo install -d -o 10001 -g 10001 /var/lib/marcedit-web/data/tasks
```

Then point the compose volume mount at `/var/lib/marcedit-web/data`
in production overrides:

```yaml
services:
  marcedit-web:
    environment:
      MARCEDIT_WEB_PROD: "1"
      MARCEDIT_WEB_AUDIT_DIR: "/app/data/audit"
      MARCEDIT_WEB_ADMINS: "alice@example.edu,bob@example.edu"
    volumes:
      - /var/lib/marcedit-web/data:/app/data
```

## Audit log

* Location: `data/audit/audit-YYYY-MM-DD.log` (one JSONL file per UTC
  day). Override via `MARCEDIT_WEB_AUDIT_DIR`.
* Format: one JSON object per line, with fields `ts`, `kind`, `user`,
  plus event-specific fields.
* Rotation: configure logrotate on the host; the app only appends.

Event kinds emitted today:

* `upload-accepted`, `upload-rejected` (Home, Diff sides, Marc Tools)
* `tasksfile-imported`, `tasksfile-rejected`
* `archive-imported`, `archive-rejected` (MarcEdit `.task` zip)
* `task-saved`, `task-deleted`
* `task-run-completed` (per Tasks run; task names, in/out/changed
  /error counts, returncode, timed_out)
* `conversion-issued` (Marc Tools conversion completed; kind, source
  bytes, output bytes)
* `admin-action` (admin Code-view save)
* `sandbox-timeout`, `sandbox-nonzero-exit`
* `anonymous-action-refused` (prod mode only)

Downloads of bytes the cataloger already had access to upload are
**not** audited by design — they aren't security-relevant in this
app's threat model. Add reverse-proxy egress logging if your
deployment requires it.

## Smoke tests after deploy

1. Hit `https://marcedit-web.example.edu/` while logged out → should
   redirect to Shibboleth, then return to the loaded app.
2. Confirm the sidebar shows the eppn / username, not "anonymous".
3. Confirm `id` inside the container returns `uid=10001(marcedit)`
   (not `0`).
4. Tail `data/audit/audit-$(date -u +%F).log` — uploads, task
   saves/deletes, sandbox timeouts/exits, and (in prod mode) any
   anonymous refusals should appear there. Page renders themselves
   are not logged.
5. Bypass-attempt sanity: hit the Streamlit port directly from
   another container (`curl -H 'REMOTE_USER: ' http://app:8501/`) →
   should land on the login-needed banner with an audit row noting
   the refusal.
