# marcedit-web — production deployment

This guide covers the production setup ops needs to run marcedit-web
behind nginx + Shibboleth on the RedHat 9 host. Dev defaults are
permissive (anonymous sessions allowed, audit log under `data/`); this
document captures the env-var flips and reverse-proxy rules that turn
that off.

## Image build and pull paths

There are two supported container paths:

1. Local development builds from source:

  ```bash
  docker compose up -d --build
  ```

2. Production-style runs from a pulled image:

  ```bash
  export MARCEDIT_WEB_IMAGE=ghcr.io/OWNER/REPO:latest
  docker compose -f docker-compose.pull.yml pull
  docker compose -f docker-compose.pull.yml up -d
  ```

The pull-only compose file has no `build:` section and no source-code
bind mounts. It only mounts the runtime data directory into `/app/data`.

The GitHub Actions workflow publishes images to
`ghcr.io/<owner>/<repo>` on pushes to `main`, version tags, and manual
dispatch. Public GHCR packages can be pulled anonymously. Private GHCR
packages require an operator to run `docker login ghcr.io` first.

Set these compose-time variables for pulled-image deployments when
needed:

| Var | Default | Purpose |
| --- | --- | --- |
| `MARCEDIT_WEB_IMAGE` | required | Full image reference to pull, such as `ghcr.io/OWNER/REPO:latest`. |
| `MARCEDIT_WEB_PORT` | `8501` | Host port mapped to container port `8501`. |
| `MARCEDIT_WEB_DATA_DIR` | `./data` | Host directory mounted at `/app/data`; must be writable by uid/gid `10001`. |

## Environment variables

| Var | Default | Purpose |
| --- | --- | --- |
| `MARCEDIT_WEB_PROD` | unset | When `1`/`true`/`yes`, the app refuses anonymous sessions: every page shows the login-needed banner and emits an `anonymous-action-refused` audit event. Leave unset for dev. |
| `MARCEDIT_WEB_ADMINS` | unset | Comma-separated allowlist of eppns / `REMOTE_USER` values that get the **Code view** in the Tasks editor. Anyone not listed sees only the form-builder. The wildcard `*` grants admin to everyone (dev escape hatch — never set in prod). |
| `MARCEDIT_WEB_AUDIT_DIR` | `data/audit` | Where the JSONL audit log is written. Make sure the mounted host directory is writable by uid `10001`. |
| `MARCEDIT_WEB_DB_PATH` | `data/marcedit.db` | SQLite database for audit events (TASK-049), and soon tasks + uploads (TASK-050/051). Same writability requirement as the audit dir. |
| `MARCEDIT_WEB_MAX_UPLOAD_BYTES` | `2147483648` (2 GB) | Batch upload cap (per file, MARC `.mrc`). Files are streamed to a per-session temp dir; lazy-read on demand. Matches the Diff per-file cap and the Streamlit framework cap. |
| `MARCEDIT_WEB_MAX_DIFF_BYTES` | `2147483648` (2 GB) | Diff-page **per-file** cap. Each uploaded file streams to a per-session temp dir and is mmap'd on use, so multi-GB total uploads no longer pin Python memory and there's no per-side aggregate cap. |
| `MARCEDIT_WEB_MAX_TASKSFILE_BYTES` | `1048576` (1 MB) | Tasksfile import cap (text). |
| `MARCEDIT_WEB_MAX_SESSION_BYTES` | `4294967296` (4 GB) | Aggregate per-session upload cap. Protects shared container disk against a single session accumulating many large batches. |
| `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` | 2048 (set in `docker-compose.yml`) | Streamlit's framework-level cap, in MB. Per-feature caps above this are the actually-enforced limits. |

## Trust model

The app supports two coexisting identity sources:

1. **Google OAuth** (TASK-047) — Streamlit native `st.login` flow.
   Operator opt-in: provide `.streamlit/secrets.toml` with an
   `[auth.google]` block. Streamlit drives the OIDC handshake,
   issues a session cookie, and exposes the signed-in user via
   `st.user.email`.
2. **Shibboleth** — campus federated login, terminated by nginx.

`marcedit_web.lib.identity.current_user()` resolves identity in
this order: `st.user.email` (OAuth) > `REMOTE_USER` (Shibboleth) >
`eppn` (Shibboleth) > `"anonymous"`. In prod mode (`MARCEDIT_WEB_PROD=1`),
an anonymous result is refused via `session.enforce_auth()` — the
page never renders. Either identity source counts as authenticated.

The app does **not** terminate Shibboleth itself and never re-verifies
the proxy header signature. Trust the reverse proxy or stop here.
OAuth tokens are validated by Streamlit; the app trusts Streamlit's
OIDC implementation for client-side flow handling, PKCE, and
session cookies.

## Google OAuth (dev / staging)

For local development and early-rollout deployments that don't yet
have Shibboleth in front, Streamlit native OAuth gives every user a
real identity. The setup lives in `.streamlit/secrets.toml`
(gitignored — see `.streamlit/secrets.toml.example` for the template).

**One-time Google Cloud setup:**

1. Cloud Console → APIs & Services → Credentials → Create
   Credentials → OAuth client ID → Web application.
2. Under "Authorized redirect URIs", add the redirect URI for each
   environment that uses this client:
   * Local dev: `http://localhost:8501/oauth2callback`
   * Staging: `https://<host>/oauth2callback`
3. Copy the generated client ID and client secret.

**Container setup:**

1. Copy the template:
   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```
2. Fill in `client_id`, `client_secret`, and a strong random
   `cookie_secret`:
   ```bash
   python -c 'import secrets; print(secrets.token_urlsafe(64))'
   ```
   Rotating `cookie_secret` invalidates every existing session
   (intended behavior).
3. Ensure `redirect_uri` in `[auth]` matches the URI you registered
   with Google.
4. Restart the container so Streamlit picks up the new secrets.

**Admin allowlist:** `MARCEDIT_WEB_ADMINS` keeps working — put
Google emails in it the same way you'd put eppns there.

**OAuth + Shibboleth coexistence:** Both can be live simultaneously.
If a user is signed in via Google AND a `REMOTE_USER` header is
present, OAuth wins (their Google email is the recorded identity).
This is intentional: it matches operator intent ("I'm signed in as
alice@example.edu") over reverse-proxy passthrough.

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

Two surfaces, both written for every event (TASK-049):

* **JSONL** — `data/audit/audit-YYYY-MM-DD.log` (one file per UTC day).
  Override via `MARCEDIT_WEB_AUDIT_DIR`. One JSON object per line with
  fields `ts`, `kind`, `user`, plus event-specific fields. Configure
  logrotate on the host; the app only appends. This is the operator's
  tail/grep surface.
* **SQLite** — `audit_events` table in `data/marcedit.db`. Columns:
  `id`, `ts`, `user_email`, `kind`, `payload_json`. Indexed on
  `(user_email, ts)` and `(kind, ts)`. Query with `sqlite3` or any
  SQLite client. This is the analyst's query surface.

The two surfaces share a timestamp per event so JSONL and SQL rows
can be correlated. A failure in either path doesn't block the other
or the user's action — both writes are independently wrapped. The
JSONL path will be retired in a future ticket once SQL is proven.

## Database (SQLite)

* Location: `data/marcedit.db` (override via `MARCEDIT_WEB_DB_PATH`).
* Side-files: `*.db-wal`, `*.db-shm` (WAL mode is enabled for write
  concurrency; both files must be writable by uid `10001`).
* Backup: stop the container, copy the three files (`*.db`,
  `*.db-wal`, `*.db-shm`), restart. Or use `sqlite3 ... ".backup"`
  online without a stop.
* Schema version: tracked in the `_schema_version` table. v1 added
  ``audit_events`` (TASK-049). v2 added ``tasks`` (TASK-050).
  Upload persistence (TASK-051) will bump again.

### Tasks (TASK-050)

Tasks live in the SQL ``tasks`` table with columns ``owner_email``,
``name``, ``description``, ``body``, ``extra_imports``,
``visibility`` (``private`` | ``shared``), ``created_at``,
``updated_at``. Private tasks are owner-only; shared tasks are
visible to everyone but only the owner can edit or delete.

On first boot at schema v2, the migration imports the legacy
``data/tasks/users/<slug>/*.py`` and ``data/tasks/shared/*.py``
files into ``tasks`` rows. Shared-dir files land under the sentinel
owner ``__shared__``; visibility is ``shared``. The original files
are left on disk as a manual operator backup — clear them once
the SQL store is proven.

At render time, the Tasks page materializes each visible task as a
``.py`` file under ``/tmp/marcedit-web-tasks-<sid>/`` so the Python
importer can load them. The materialized dir is per-session and
cleaned by the existing ``/tmp`` cleanup cron documented in the
Runtime temp files section.

### Persisted uploads (TASK-051)

When a signed-in cataloger uploads a ``.mrc`` file, the bytes go to
a stable path under ``data/uploads/<safe_user_slug>/upload.mrc``
and a row in the ``uploads`` table tracks ``filename``,
``record_count``, ``file_bytes``, and an ``active`` flag. Each
user has at most one ``active=1`` row at a time — re-uploading
supersedes the previous file.

On session init (every page hit), if the user is signed in and
``st.session_state["store"]`` is empty (typical after a hard
browser refresh), ``session.restore_active_upload`` reattaches the
on-disk file as a ``RecordStore``. An ``upload-restored`` audit
event is emitted on success.

Anonymous users get no DB row by design — refresh loses their
upload. "Sign in to keep your work" is the explicit product
choice (see TASK-051).

Operator considerations:

* The ``data/uploads/`` directory must be writable by uid `10001`
  (the same constraint as ``data/audit/`` and ``data/marcedit.db``).
* Disk usage: at most one upload per signed-in user. Plan for the
  worst-case sum of cataloger upload sizes if many users are
  active simultaneously.
* Backup: included in the same ``data/`` mount the rest of the
  app's runtime state uses.

Event kinds emitted today:

* `upload-accepted`, `upload-rejected` (Home, Diff sides, Marc Tools)
* `tasksfile-imported`, `tasksfile-rejected`
* `archive-imported`, `archive-rejected` (MarcEdit `.task` zip)
* `task-saved`, `task-deleted`
* `task-run-completed` (per Tasks run; task names, in/out/changed
  /error counts, returncode, timed_out)
* `batch-replace-applied` (Quick find/replace Apply; matched/applied
  /changed counts plus field scope)
* `conversion-issued` (Marc Tools conversion completed; kind, source
  bytes, output bytes)
* `dedupe-deletes-issued` (Dedupe deletes export built; strategy +
  params + total groups + delete count)
* `admin-action` (admin Code-view save)
* `sandbox-timeout`, `sandbox-nonzero-exit`
* `anonymous-action-refused` (prod mode only)

Downloads of bytes the cataloger already had access to upload are
**not** audited by design — they aren't security-relevant in this
app's threat model. Add reverse-proxy egress logging if your
deployment requires it.

Example logrotate policy:

```text
/var/lib/marcedit-web/data/audit/*.log {
    daily
    rotate 180
    compress
    missingok
    notifempty
    create 0640 10001 10001
}
```

## Runtime temp files

The app writes large per-session working files under `/tmp` with
`marcedit-web-*` prefixes. Normal Streamlit reruns reuse these paths,
but abrupt browser closes or container crashes can leave old directories
behind. In long-lived containers, add a conservative cleanup job such as:

```bash
docker exec marcedit-web find /tmp \
  -maxdepth 1 -type d -name 'marcedit-web-*' -mtime +2 -print -exec rm -rf {} +
```

Use an age threshold that is longer than any expected active cataloging
session.

## Accessibility

The app targets **WCAG 2.1 AA** for the content we control. The
boundary worth knowing about during accessibility reviews:

**App-controlled (auditable in this repo):**

* Heading hierarchy — every page steps h1 → h2 → h3 without
  gaps (TASK-054).
* Label text on every form widget — Streamlit's
  ``st.text_input`` / ``st.checkbox`` / ``st.button`` all carry
  visible labels in the app.
* Loading indicators on every long-running operation
  (``st.spinner`` / ``st.status``, TASK-052) so screen-reader
  users hear progress instead of silence.
* Severity color coding plus icon labels on the Validate table —
  color is not the sole information channel (TASK-053).
* ``unsafe_allow_html=True`` callsites have trust-source comments
  identifying the input as operator-controlled or escaped; the
  Diff renderer runs every cell through ``html.escape``.

**Streamlit-framework provided:**

* Color contrast in the bundled light theme (4.5:1+ on body text).
* Focus rings on interactive widgets.
* Semantic HTML for buttons, inputs, tables (``st.dataframe``
  renders a ``role="grid"`` virtualized table).
* Keyboard navigation between widgets via Tab.

**Out of our control:**

* The Streamlit chrome (top toolbar, sidebar collapse button,
  menu). These ship as part of the framework; we hide the dev
  toolbar via ``[client] toolbarMode = "minimal"`` but the
  remaining surface is Streamlit's responsibility.

**Running a manual audit:**

1. Open the running container in Chrome.
2. Open DevTools → Lighthouse → Accessibility audit; expect a
   "good" or better score on each page.
3. Optionally install axe DevTools as an extension and run it on
   each page; report any non-Streamlit-owned issues here.

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
