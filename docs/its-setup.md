# marcedit-web — ITS setup brief

> **Audience:** Smith Libraries ITS, for setting up marcedit-web at
> `https://libtools2.smith.edu/marcedit-web/`.

This is a Python 3.9 web app (Streamlit) deployed natively on
libtools2.smith.edu (RHEL 8.10). No containers are involved.
We need four one-time root operations from you, then day-to-day
deploys are self-service from the dev team.

The current state of libtools2 already provides almost everything:
Python 3.9 is installed, Apache 2.4 + mod_shib are serving other
apps, the TLS cert is valid, and there's a registered Shibboleth
SP entity. We're adding marcedit-web as a subpath of the existing
libtools2.smith.edu vhost.

## Part 1 — One-time install (you do these once)

### 1. Create the `marcedit` service user

```bash
useradd --system --shell /bin/bash --home-dir /var/www/html/marcedit-web marcedit
```

Notes:
- Shell is `/bin/bash` (not `/sbin/nologin`) because `sudo -iu marcedit`
  invokes the target user's login shell, and the dev deploy script
  runs in an interactive marcedit shell. Direct login as marcedit
  is prevented by the absence of a password.
- No `--create-home` flag: the home directory is the repo location,
  which the dev account will populate by cloning the repo there.

### 2. Drop the sudoers fragment

Install `deploy/marcedit.sudoers` from the repo to `/etc/sudoers.d/marcedit`:

```bash
install -m 0440 /var/www/html/marcedit-web/deploy/marcedit.sudoers \
    /etc/sudoers.d/marcedit
visudo -cf /etc/sudoers.d/marcedit
```

This lets the `marcedit` account restart the private app and start, stop, or
restart the durable worker through exact command rules. The named dev account
(`roconnell`) may `sudo -iu marcedit` to run deploys. It does not grant the
service user unrestricted root or `systemctl` access.

### 3. Install the private app and worker systemd units

```bash
install -m 0644 \
    /var/www/html/marcedit-web/deploy/marcedit-web-private.service \
    /etc/systemd/system/marcedit-web-private.service
install -m 0644 \
    /var/www/html/marcedit-web/deploy/marcedit-web-worker.service \
    /etc/systemd/system/marcedit-web-worker.service
systemctl daemon-reload
# Wait to enable until after the venv exists (see Verification below).
```

The private app owns the authenticated Streamlit port and runs additive schema
migrations during readiness. The worker uses the same `marcedit` user, `.env`,
SQLite database, and `data/` tree but opens no network port. Do not install the
legacy `marcedit-web.service` alongside this two-service private deployment.

### 4. Add the Apache `<Location>` block

Open the existing `libtools2.smith.edu` vhost config (likely
`/etc/httpd/conf.d/libtools2.conf` or similar) and paste in the
contents of `/var/www/html/marcedit-web/deploy/libtools2-marcedit.conf.snippet`
inside the existing `<VirtualHost *:443>` block.

The snippet's `<Location>` block `Include`s an attestation secret file
(TASK-073) — create it first, or `configtest` will fail on the missing
include. Generate one secret and install it; the SAME value goes in the app's
`.env` as `MARCEDIT_WEB_PROXY_SECRET` (the dev team fills that in):

```bash
SECRET=$(openssl rand -hex 32)
install -o root -g apache -m 0640 \
    /var/www/html/marcedit-web/deploy/marcedit-web-attestation.conf.example \
    /etc/httpd/marcedit-web-attestation.conf
sed -i "s/REPLACE_WITH_SECRET/$SECRET/" /etc/httpd/marcedit-web-attestation.conf
echo "Give this to the dev team for .env MARCEDIT_WEB_PROXY_SECRET: $SECRET"
```

Keep the file **outside** `conf.d/` (so Apache's `*.conf` autoglob does not set
the header on every vhost) and `0640 root:apache` (so the secret is not
world-readable on the shared host). Without it the app refuses all header
identity and every cataloger shows as `anonymous`.

Then test the Apache config and reload:

```bash
apachectl configtest
systemctl reload httpd
```

**Compatibility note:** The snippet uses `RequestHeader set REMOTE_USER "expr=%{REMOTE_USER}"`
syntax that works on mod_shib 3.1+. If the installed mod_shib on
libtools2 is older 3.0.x, this may need to change to
`RequestHeader set REMOTE_USER %{REMOTE_USER}e`. Symptom: the app
sidebar shows "anonymous" after a successful Shib login. The fix
is documented in a comment inside the snippet.

## Part 2 — Verification

Ask the dev team to do their part:

1. `cd /var/www/html && git clone <repo URL> marcedit-web` (as the
   dev account; chown to marcedit:marcedit afterwards)
2. `sudo -iu marcedit bash scripts/install.sh` — creates the venv,
   installs deps, ensures data subdirs exist
3. Copy `.env.example` to `.env` and fill in production values —
   including `MARCEDIT_WEB_PROXY_SECRET`, which MUST equal the secret ITS
   put in `/etc/httpd/marcedit-web-attestation.conf` (step 4)
4. Optionally copy `.streamlit/secrets.toml.example` to
   `.streamlit/secrets.toml` for Google OAuth

Run preflight after install and `.env` configuration so it can verify the
installed worker unit, writable `data/operations` root, and positive queue
chunk/retention settings without creating or revealing configuration values:

```bash
bash /var/www/html/marcedit-web/scripts/preflight-check.sh
```

You should see green checks for Python 3.9, Apache modules, the `marcedit` user,
data and operations-directory writability, the worker unit, and queue settings.

When that's done, enable and start the private app before the worker:

```bash
systemctl enable --now marcedit-web-private
systemctl enable --now marcedit-web-worker
systemctl status marcedit-web-private marcedit-web-worker
```

Then confirm end-to-end:

```bash
curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health
# expected: "ok"

cd /var/www/html/marcedit-web
/var/www/html/marcedit-web/.venv/bin/python -m marcedit_web.ops.worker --check
# expected: "ok"

curl -I https://libtools2.smith.edu/marcedit-web/
# expected: 302 redirect to Shibboleth
```

Finally, open `https://libtools2.smith.edu/marcedit-web/` in a
browser, complete the Shib login, and confirm the sidebar shows
your eppn (not "anonymous").

## Part 3 — Day-to-day ops

After install, all deploys are self-service from the dev team:

```bash
sudo -iu marcedit
cd /var/www/html/marcedit-web
bash scripts/deploy.sh
```

The deploy script stops the worker before changing code, waits for its previous
heartbeat to expire, pulls main, refreshes the venv, restarts the private app,
and verifies HTTP plus database readiness. Only then does it start the worker
and require a fresh heartbeat. If any step fails, it leaves the worker stopped
so queued work remains durable and recoverable.

An interrupted running operation is recovered from its immutable input after
its lease expires; partial attempt output is not published. A cancellation
request remains durable during deployment and is finalized rather than
restarted. Users may cancel queued or running work from the Operations page.

### Log locations

- Private app stdout/stderr: `journalctl -u marcedit-web-private`
- Durable worker stdout/stderr: `journalctl -u marcedit-web-worker`
- Audit log (JSONL, one file per UTC day): `/var/www/html/marcedit-web/data/audit/audit-YYYY-MM-DD.log`
- Apache access/error: wherever libtools2's vhost already logs

### Audit log rotation

Sample logrotate policy (drop in `/etc/logrotate.d/marcedit-web`):

```
/var/www/html/marcedit-web/data/audit/*.log {
    daily
    rotate 180
    compress
    missingok
    notifempty
    create 0640 marcedit marcedit
}
```

### Backups

The mutable state lives in `/var/www/html/marcedit-web/data/`:

- `marcedit.db` (+ `.db-wal`, `.db-shm`) — SQLite audit + tasks + uploads index
- `audit/*.log` — JSONL audit log
- `tasks/*.py` — legacy file-backed tasks (kept as backup; SQL is canonical)
- `uploads/<user>/jobs/<job-id>/<upload-id>/upload.mrc` — persisted per-upload MARC files
- `operations/` — immutable queued inputs and retained result artifacts

Stop the worker before the private app, then back up the complete `data/` tree
as one recovery generation. Start the private app before the worker after the
snapshot:

```bash
systemctl stop marcedit-web-worker
systemctl stop marcedit-web-private
rsync -a /var/www/html/marcedit-web/data/ /your/backup/target/data/
systemctl start marcedit-web-private
systemctl start marcedit-web-worker
```

See `docs/deployment.md` for the coordinated SQLite backup/restore commands and
configured job-file and operations-root handling.
