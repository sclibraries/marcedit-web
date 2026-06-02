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

This grants two NOPASSWD permissions: the marcedit account can
`systemctl restart marcedit-web`, and the named dev account
(`roconnell`) can `sudo -iu marcedit` to run deploys.

### 3. Install and enable the systemd unit

```bash
install -m 0644 /var/www/html/marcedit-web/deploy/marcedit-web.service \
    /etc/systemd/system/marcedit-web.service
systemctl daemon-reload
# Wait to enable until after the venv exists (see Verification below).
```

### 4. Add the Apache `<Location>` block

Open the existing `libtools2.smith.edu` vhost config (likely
`/etc/httpd/conf.d/libtools2.conf` or similar) and paste in the
contents of `/var/www/html/marcedit-web/deploy/libtools2-marcedit.conf.snippet`
inside the existing `<VirtualHost *:443>` block.

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

Run the preflight script from the repo:

```bash
bash /var/www/html/marcedit-web/scripts/preflight-check.sh
```

You should see green checks for: python3.9, all Apache modules,
marcedit user, data directory writability.

Then ask the dev team to do their part:

1. `cd /var/www/html && git clone <repo URL> marcedit-web` (as the
   dev account; chown to marcedit:marcedit afterwards)
2. `sudo -iu marcedit bash scripts/install.sh` — creates the venv,
   installs deps, ensures data subdirs exist
3. Copy `.env.example` to `.env` and fill in production values
4. Optionally copy `.streamlit/secrets.toml.example` to
   `.streamlit/secrets.toml` for Google OAuth

When that's done, you enable + start the service:

```bash
systemctl enable --now marcedit-web
systemctl status marcedit-web
```

Then confirm end-to-end:

```bash
curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health
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

The deploy script pulls main, refreshes the venv, restarts the
service via the NOPASSWD sudoers rule, and polls the healthcheck.

### Log locations

- App stdout/stderr: `journalctl -u marcedit-web`
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
- `uploads/<user>/upload.mrc` — persisted per-user uploads

`rsync` this directory to your preferred backup target.
