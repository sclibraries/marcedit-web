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
├── data/                        # SQLite and durable artifacts (marcedit-owned)
│   ├── marcedit.db              # SQLite (WAL mode)
│   ├── marcedit.db-wal
│   ├── marcedit.db-shm
│   ├── audit/audit-YYYY-MM-DD.log
│   ├── job-files/<file-id>/versions/vNNNNNN.mrc
│   ├── job-files/<file-id>/exports/*.mrc
│   ├── operations/<operation-id>/
│   ├── tasks/
│   └── uploads/<user>/jobs/<job-id>/<upload-id>/upload.mrc
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
| `MARCEDIT_WEB_JOB_FILES_ROOT` | Immutable job-file versions and retained exports; defaults to `data/job-files`. |
| `MARCEDIT_WEB_OPERATIONS_ROOT` | Durable queued inputs, candidates, and attempt workspaces; defaults to `data/operations` and must stay below the service-writable `data/` root. |
| `MARCEDIT_WEB_QUEUE_CHUNK_RECORDS` | Positive record count processed per sandbox chunk; defaults to `5000`. |
| `MARCEDIT_WEB_OPERATION_RETENTION_DAYS` | Positive number of days to retain queue-owned Quick Load files and unapplied Job candidates; defaults to `30`. |
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

The authenticated application uses `marcedit-web-private.service`; its durable
queue runs independently in `marcedit-web-worker.service`. The public unit does
not read the queue database or start queued work.

```bash
sudo systemctl status marcedit-web-private marcedit-web-worker
sudo systemctl restart marcedit-web-private
sudo systemctl restart marcedit-web-worker
journalctl -u marcedit-web-private -f
journalctl -u marcedit-web-worker -f
```

Private service startup runs a readiness probe before Streamlit starts:

```bash
sudo -u marcedit /var/www/html/marcedit-web/.venv/bin/python \
    -m marcedit_web.ops.health
```

The probe initializes the schema if needed and verifies the SQLite database
accepts a rollbacked write transaction. This is intentionally stricter than
Streamlit's built-in `/_stcore/health`, which only proves the process is
serving HTTP.

Verify that the worker has written a heartbeat within the last 15 seconds:

```bash
cd /var/www/html/marcedit-web
/var/www/html/marcedit-web/.venv/bin/python -m marcedit_web.ops.worker --check
```

A failed check means the worker is stopped, repeatedly failing its readiness
probe, or cannot write the shared SQLite database. Inspect both service status
and `journalctl -u marcedit-web-worker`; correlate failures with the operation
ID shown in the in-app Operations history. Logs intentionally omit MARC record
contents, task bodies, and credentials.

### Queue behavior during deploy and recovery

`scripts/deploy.sh` stops the worker before pulling code so an old worker cannot
write while the private app applies an additive schema migration. It starts the
worker only after HTTP and database readiness pass, then requires a fresh
heartbeat. If deployment fails, the worker remains stopped and queued work stays
durable in SQLite.

An operation interrupted while running keeps its immutable input and lease. On
the next healthy worker start, an expired running lease is requeued and starts
again from that input; partial attempt output is never published. An interrupted
cancellation remains a cancellation request and is finalized rather than
restarted. Users may also cancel queued or running work from the Operations page.

The worker removes expired queue-owned Quick Load files and unapplied Job
candidates during idle maintenance. They are retained for 30 days by default;
set `MARCEDIT_WEB_OPERATION_RETENTION_DAYS` to another positive integer in
`.env` when policy requires it. Audit rows, events, bounded errors, and applied
immutable Job versions are not removed by this cleanup.

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

### Large-batch memory guardrails (TASK-147)

Job-file originals, versions, exports, and large-batch candidates remain
disk-backed rather than being retained as whole in-memory batches. Concurrent
operations still consume CPU, temporary disk capacity, and worker time, so the
admission limit and host free-space monitoring remain operational constraints.

The private unit starts cgroup reclaim at `MemoryHigh=1536M` and retains the
hard `MemoryMax=2G` ceiling. The application admits two saved-task or quick
batch operations at a time by default. Set
`MARCEDIT_WEB_MAX_CONCURRENT_BATCHES` in `.env` only after repeating the
concurrent smoke test below; lowering it to `1` trades throughput for more
headroom.

RHEL 8 defaults to cgroup v1 unless the unified hierarchy was explicitly
enabled. Check the host before configuring a per-service swap limit:

```bash
stat -fc %T /sys/fs/cgroup
systemd --version | head -1
```

If and only if the first command prints `cgroup2fs`, add the v2-only swap
drop-in:

```bash
sudo systemctl edit marcedit-web-private.service
```

```ini
[Service]
MemorySwapMax=0
```

On cgroup v1, leave that drop-in absent. In either case, reload, restart, and
verify the effective settings rather than assuming the checked-in unit was
installed correctly:

```bash
sudo systemctl daemon-reload
sudo systemctl restart marcedit-web-private.service
systemctl show marcedit-web-private.service \
  -p MemoryCurrent -p MemoryHigh -p MemoryMax -p MemorySwapMax
```

For cgroup v2, inspect the kernel counters directly:

```bash
CGROUP=$(systemctl show marcedit-web-private.service -p ControlGroup --value)
cat "/sys/fs/cgroup${CGROUP}/memory.current"
cat "/sys/fs/cgroup${CGROUP}/memory.events"
cat "/sys/fs/cgroup${CGROUP}/memory.swap.current"
```

Before increasing the admission limit, open three independent authenticated
browser sessions, load the same 100K synthetic batch in each, and start a
quick-batch preview at the same time. The first two should run while the third
waits. During the run:

```bash
watch -n 1 'systemctl show marcedit-web-private.service -p MemoryCurrent'
journalctl -u marcedit-web-private.service -f | grep batch-performance
```

Accept the configuration only when `MemoryCurrent` stays below 1.5 GB,
`memory.events` reports no `oom` or `oom_kill`, all three runs preserve the
input record count, and each completion log contains operation, phase,
elapsed time, outcome, and `peak_rss_bytes`.

Run the single-process production benchmark separately as the service user:

```bash
sudo -u marcedit /var/www/html/marcedit-web/.venv/bin/python \
  scripts/benchmark-large-batch.py --records 100000
```

It exits nonzero if last-record lookup exceeds 250 ms, the standard quick
operation exceeds 30 seconds, or record counts drift.

### Health watchdog (TASK-133)

The TASK-117 outage showed Streamlit's Runtime can die inside a live
process: `/_stcore/health` returns 503 and websockets are refused while
systemd still reports `active (running)`, so `Restart=on-failure` never
fires. `marcedit-web-watchdog.{service,timer}` closes that gap — every
2 minutes it demands an HTTP 200 from the health endpoint (three
attempts over ~20s) and restarts `marcedit-web` when all fail.

```bash
sudo cp deploy/marcedit-web-watchdog.service /etc/systemd/system/
sudo cp deploy/marcedit-web-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now marcedit-web-watchdog.timer
systemctl list-timers marcedit-web-watchdog.timer   # verify scheduling
```

The watchdog only acts on a unit systemd reports as active — a service
stopped on purpose (`systemctl stop marcedit-web` for maintenance or a
migration) stays stopped. To verify the restart path once, simulate the
zombie by freezing the process (unit stays active, health times out):

```bash
sudo systemctl kill -s SIGSTOP marcedit-web    # freeze: active but unresponsive
sudo systemctl start marcedit-web-watchdog.service   # takes ~30s, then restarts
journalctl -u marcedit-web-watchdog --no-pager | tail -5
sudo systemctl status marcedit-web             # fresh PID, running again
```

On a two-tier host the 8501 tier is `marcedit-web-private.service` —
edit both unit names inside the watchdog service before installing.

The legacy single-unit `marcedit-web.service` still ships conservative
guardrails as comments. The active 1.5/2 GB settings above belong to the
two-tier private unit used for large authenticated batches.

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

Audit retention is handled by the maintenance CLI. Run it daily from cron or a
systemd timer as the `marcedit` user:

```bash
cd /var/www/html/marcedit-web
/var/www/html/marcedit-web/.venv/bin/python \
    -m marcedit_web.ops.maintenance retention --retain-days 90
```

The command prunes `audit_events` rows older than the retention window, deletes
matching `data/audit/audit-YYYY-MM-DD.log` files, checkpoints the WAL, and runs
`VACUUM`. It prints a one-line summary with deleted row/file counts.

## Database

SQLite WAL mode at `data/marcedit.db`. Three files:
`marcedit.db`, `marcedit.db-wal`, `marcedit.db-shm`.

SQLite runs with connection-per-call access. Write paths that swap shared
state, such as active uploads and advisory locks, use explicit
`BEGIN IMMEDIATE` transactions so concurrent Streamlit sessions serialize at
the database boundary. The advisory lock table is a foundation for future
shared-job and record checkout flows; it is not a user-facing collaboration UI
by itself.

The SQLite database, `MARCEDIT_WEB_JOB_FILES_ROOT`, and
`MARCEDIT_WEB_OPERATIONS_ROOT` form one recovery unit: version, queue, and
artifact rows are not usable without their immutable MARC files. Back them up
and restore them together from the same maintenance window. The current
scriptable command captures SQLite and audit data; production backup automation
must also copy the configured job-files and operations roots into the same dated
backup while both private services remain stopped. This creates one coordinated
database-and-artifact snapshot rather than independently timed backups.
The commands below run from the trusted install directory and source its
production `.env` (the same file systemd reads) before resolving any storage
path. Do not source an untrusted environment file.

Scriptable backup during a maintenance window:

```bash
sudo systemctl stop marcedit-web-worker
sudo systemctl stop marcedit-web-private
cd /var/www/html/marcedit-web
BACKUP_DIR=/var/backups/marcedit-web/$(date -u +%F)
set -a
. ./.env
set +a
JOB_FILES_ROOT="${MARCEDIT_WEB_JOB_FILES_ROOT:-data/job-files}"
OPERATIONS_ROOT="${MARCEDIT_WEB_OPERATIONS_ROOT:-data/operations}"
/var/www/html/marcedit-web/.venv/bin/python \
    -m marcedit_web.ops.backup create "$BACKUP_DIR"
cp -a "$JOB_FILES_ROOT" "$BACKUP_DIR/job-files"
cp -a "$OPERATIONS_ROOT" "$BACKUP_DIR/operations"
sudo systemctl start marcedit-web-private
sudo systemctl start marcedit-web-worker
```

The backup command uses `sqlite3.Connection.backup`, so committed WAL content
is folded into the backed-up `marcedit.db`; it also copies `data/audit/` JSONL
logs and writes a small manifest. To restore during a maintenance window:

```bash
sudo systemctl stop marcedit-web-worker
sudo systemctl stop marcedit-web-private
cd /var/www/html/marcedit-web
BACKUP_DIR=/var/backups/marcedit-web/YYYY-MM-DD
set -a
. ./.env
set +a
JOB_FILES_ROOT="${MARCEDIT_WEB_JOB_FILES_ROOT:-data/job-files}"
OPERATIONS_ROOT="${MARCEDIT_WEB_OPERATIONS_ROOT:-data/operations}"
/var/www/html/marcedit-web/.venv/bin/python \
    -m marcedit_web.ops.backup restore "$BACKUP_DIR"
rm -rf "$JOB_FILES_ROOT"
mkdir -p "$(dirname "$JOB_FILES_ROOT")"
cp -a "$BACKUP_DIR/job-files" "$JOB_FILES_ROOT"
rm -rf "$OPERATIONS_ROOT"
mkdir -p "$(dirname "$OPERATIONS_ROOT")"
cp -a "$BACKUP_DIR/operations" "$OPERATIONS_ROOT"
sudo systemctl start marcedit-web-private
sudo systemctl start marcedit-web-worker
```

Cold-copy fallback: stop the worker and private app, copy `marcedit.db`,
`marcedit.db-wal`, `marcedit.db-shm`, `data/audit/`, and the complete job-files
and operations roots as one set, then start the app before the worker. Never
restore the database and artifact roots from different backup generations.

Schema version tracked in the `_schema_version` table. v1 added
`audit_events` (TASK-049); v2 added `tasks` (TASK-050); v3 added
uploads (TASK-051); v4 added `users` and `allowed_domains` (TASK-088);
v5 added `advisory_locks` (TASK-083); v6 added `jobs`, `job_access`, and
`uploads.job_id` (TASK-081); v7 added `job_snapshots` (TASK-082); v8 added
`job_versions` (TASK-094). Migrations run on first request and are idempotent.

The job workflow supports shared asynchronous handoffs: owners and editors can
invite collaborators, check out a file, return an immutable version for review,
approve it, and resume from authoritative state after refresh. Checkout and
stale-version checks serialize mutations; this is not simultaneous Google
Docs-style editing of the same file.

## Smoke tests after deploy

1. `sudo -u marcedit /var/www/html/marcedit-web/.venv/bin/python -m marcedit_web.ops.health` →
   should print `ok`.
2. `curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health` →
   should print `ok`.
3. `curl -I https://libtools2.smith.edu/marcedit-web/` while logged
   out → should redirect to Shibboleth.
4. After Shib login, the sidebar should show the cataloger's eppn,
   not `anonymous`.
5. `sudo systemctl show -p MainPID marcedit-web | xargs -I {} ps -o user= -p {}` →
   should report `marcedit` (not `root`, not `apache`).
6. Tail today's audit log — `tail -F /var/www/html/marcedit-web/data/audit/audit-$(date -u +%F).log` —
   then perform an upload through the UI; an `upload-accepted` event
   should appear.
7. Forged-header refusal — `curl -s -H 'REMOTE_USER: someone@smith.edu'
   http://127.0.0.1:8501/marcedit-web/` sent straight to the backend
   (bypassing Apache) must NOT yield an identified/admin session: in prod it
   is refused and the sidebar shows `anonymous`, never the forged eppn.

## Runtime temp files

The app writes large per-session working files under `/tmp` with
`marcedit-web-*` prefixes. With `PrivateTmp=true`, the host sees them below a
`systemd-private-*` directory. Abrupt browser closes can leave old directories
behind. Add a conservative cleanup job that covers both layouts:

```bash
find /tmp -xdev -type d \
  \( -path '/tmp/marcedit-web-*' \
     -o -path '/tmp/systemd-private-*/tmp/marcedit-web-*' \) \
  -mtime +2 -print -exec rm -rf {} +
```

Run this as root from a daily cron during a low-traffic window. The
`marcedit` user cannot see the host-side private namespace paths.

## Accessibility

The app targets WCAG 2.1 AA for content the app controls. See the
accessibility section in `marcedit_web/render/*` source comments
and TASK-054 for the audited boundary.

## Two-tier deployment (TASK-088)

marcedit-web supports a dual-unit deployment model to safely expose a
limited public interface (for anonymous users) without compromising the
authenticated cataloger tier. Both units run the same artifact (installed at
`/var/www/html/marcedit-web`, same as `marcedit-web.service`), but are
configured via environment variables to select different feature sets.

**Relationship to `marcedit-web.service`:** The two-tier units
(`marcedit-web-private.service` and `marcedit-web-public.service`) supersede
the single `marcedit-web.service` when two-tier mode is deployed. Do not run
all three simultaneously on the same host — disable `marcedit-web.service`
before enabling the two-tier pair.

### Architecture

Two systemd units share the same binary but bind to different loopback ports:

| Unit | Port | Mode | Purpose |
| --- | --- | --- | --- |
| `marcedit-web-private.service` | 8501 | `MARCEDIT_WEB_MODE=private` | Authenticated catalog, task sandbox, uploads (internal use) |
| `marcedit-web-public.service` | 8502 | `MARCEDIT_WEB_MODE=public` | Anonymous light tier: Home, View, Validate, Report, Marc Tools only |

The reverse proxy (Apache):
- Routes requests to `https://libtools2.smith.edu/marcedit-web/` → `:8501` (private unit) after Shibboleth authentication.
- Routes requests to `https://marcedit-open.smith.edu/` → `:8502` (public unit) without auth.
- Terminates TLS.
- Applies per-IP rate limiting in front of the public unit (recommended: 30 req/min).
- Never forwards the proxy attestation secret to the public unit.

### Configuration

**Private unit — proxy attestation secret injection:**

The private unit loads `/var/www/html/marcedit-web/.env` via `EnvironmentFile=`,
the same mechanism used by `marcedit-web.service`. That file must contain
`MARCEDIT_WEB_PROXY_SECRET`. Follow the same setup steps documented in
`deploy/marcedit-web-attestation.conf.example`:

```bash
# 1. Generate a shared secret (same value goes in Apache and .env):
openssl rand -hex 32

# 2. Add the secret to the app's environment file:
echo 'MARCEDIT_WEB_PROXY_SECRET=<paste-secret-here>' \
  >> /var/www/html/marcedit-web/.env
chmod 0640 /var/www/html/marcedit-web/.env
chown root:marcedit /var/www/html/marcedit-web/.env

# 3. Put the same value in the Apache include (outside conf.d/):
install -o root -g apache -m 0640 \
  deploy/marcedit-web-attestation.conf.example \
  /etc/httpd/marcedit-web-attestation.conf
# Edit /etc/httpd/marcedit-web-attestation.conf, replace REPLACE_WITH_SECRET.
systemctl reload httpd
```

The proxy attestation secret is **never** forwarded to the public unit — the
public unit carries no `EnvironmentFile=` and no `MARCEDIT_WEB_PROXY_SECRET`.

**Private unit environment (set in the systemd unit file):**

```bash
MARCEDIT_WEB_MODE=private
MARCEDIT_WEB_PROD=1
MARCEDIT_WEB_DB_PATH=/var/www/html/marcedit-web/data/marcedit.db
MARCEDIT_WEB_ADMIN_EMAILS=roconnell@smith.edu  # Comma-separated
MARCEDIT_WEB_ALLOWED_DOMAINS=smith.edu,umass.edu,mtholyoke.edu,amherst.edu,hampshire.edu
# MARCEDIT_WEB_PROXY_SECRET — loaded from EnvironmentFile= (.env), not set inline.
```

See `deploy/marcedit-web-private.service` for the full systemd unit.

**Public unit environment:**

```bash
MARCEDIT_WEB_MODE=public
MARCEDIT_WEB_MAX_UPLOAD_BYTES=5242880  # 5 MB
# No MARCEDIT_WEB_PROD, no DB path, no OAuth, no proxy secret.
```

The public unit **intentionally has no catalog database and no sandbox page**.
These are accessed only in private mode. This is enforced in code: in public
mode `audit_event` never calls `db.init_schema()` and never opens the catalog
DB, regardless of whether the filesystem is writable. No DB path needs to be
set in the public unit's environment, and none is created at runtime.
See `deploy/marcedit-web-public.service` for the full systemd unit.

### Resource isolation

Both units are subject to cgroup constraints (TASK-075):

| Unit | Memory | CPU |
| --- | --- | --- |
| Private | 2 GB | 200% (2 cores) |
| Public | 1 GB | 100% (1 core) |

This ensures that anonymous abuse (high upload volume, resource-exhaustive
validation) cannot starve the private unit and impact catalogers.

### Scalability and concurrency limits

**Important:** The public unit is still a single-process Streamlit
application. Its concurrency ceiling is the same order as the private unit —
bounded by Streamlit's synchronous session model, not scalable horizontally.
The rate limit (30 req/min default) + byte cap (5 MB) + separate resource
budget (1 GB / 1 core) are operational controls that reduce the blast radius
of abuse, but they do **not** make the public unit horizontally scalable or
suitable for high-throughput anonymous workloads. Use load balancing and
multiple instances only if you replace Streamlit with a async-first framework.

### Bootstrap and initial setup

On private-unit startup, `db.init_schema()` seeds access state from two
environment variables:

- `MARCEDIT_WEB_ADMIN_EMAILS`: comma-separated trusted first-admin emails.
  Each listed email is promoted to `users.role='admin'` and
  `users.status='approved'`. This can recover an existing pending row when
  an admin first logged in before the env var was present.
- `MARCEDIT_WEB_ALLOWED_DOMAINS`: comma-separated domains that auto-approve
  new logins as catalogers. These domains are stored in `allowed_domains`.

Unknown users whose domain is not in `allowed_domains` are inserted into
`users` with `status='pending'`. An approved admin then opens the private
Admin page and approves or denies those pending users. Normal approvals should
go through that UI; manual SQLite edits are not the supported workflow.

Seeding is idempotent and runs on each private schema initialization. It is
promotion-only: listed admins are promoted, but omitting an existing admin from
the env var does not demote them.

### Manual smoke tests

After deploy, verify both units in separate terminals:

```bash
# Terminal 1: public unit
MARCEDIT_WEB_MODE=public \
  streamlit run marcedit_web/App.py --server.port 8502

# Terminal 2: private unit (with minimal auth setup)
MARCEDIT_WEB_MODE=private MARCEDIT_WEB_ADMIN_EMAILS=you@smith.edu \
  streamlit run marcedit_web/App.py --server.port 8501
```

Then, from a third terminal:

1. **Public unit checks:**
   - `curl http://127.0.0.1:8502/` → renders Home page.
   - Sidebar shows only: Home, View, Validate, Report, Marc Tools.
   - No Tasks page, no Code view, no Catalog.

2. **Private unit checks (dev mode, no OAuth):**
   - `curl http://127.0.0.1:8501/` → renders Home page.
   - Sidebar shows full menu: Tasks, Catalog, Uploads, Sandbox, Validate, etc.
   - (With OAuth configured: allowlisted eppns land as catalogers;
     unknown users land in pending state.)
