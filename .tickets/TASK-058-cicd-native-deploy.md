# TASK-058 — CI/CD pipeline + native-Python deploy at libtools2/marcedit-web

**Status:** Todo
**Stage:** Production deploy pathway for v3.x onward.

## Title

Build out a CI/CD pipeline for marcedit-web and move production from
the current Docker-based design to a native Python 3.9 venv deploy on
`libtools2.smith.edu/marcedit-web` (RHEL 8.10). CI gates merges on
the existing pytest suite; deploys are manual `bash deploy.sh` runs
on the server, matching the folio-report-explorer operational
pattern.

## Scope

### CI half
- Add `.github/workflows/test.yml` running `pytest` on Python 3.9
  against every push and pull request, with pip caching.
- Delete `.github/workflows/docker-publish.yml`.
- Document enabling branch protection on `main` requiring the test
  job (manual GitHub repo-settings step, called out in the spec).

### Deploy half (server-side artifacts in this repo)
- `scripts/deploy.sh` — everyday deploy: enforces it runs as the
  `marcedit` service user, `git pull origin main`, `pip install`
  into the existing venv, `sudo /bin/systemctl restart marcedit-web`,
  poll `/_stcore/health` until ready.
- `scripts/install.sh` — first-time, idempotent setup script that
  the marcedit user runs once: create venv, initial dependency
  install, ensure data directory exists with the right perms.
- `scripts/preflight-check.sh` — ITS-facing readiness check that
  reports Python 3.9 availability, Apache modules loaded
  (`mod_proxy`, `mod_proxy_http`, `mod_proxy_wstunnel`,
  `mod_headers`, `mod_rewrite`, `mod_ssl`, `mod_shib`), marcedit
  user presence, port 8501 binding scope, and write-perms on
  the data dir.
- `deploy/marcedit-web.service` — systemd unit; runs as
  `marcedit:marcedit`, binds Streamlit to `127.0.0.1:8501`,
  invokes Streamlit with `--server.baseUrlPath=marcedit-web` for
  the subpath deploy, replicates the Dockerfile's hardening at
  the systemd layer (`NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome=true`, `PrivateTmp=true`, `ReadWritePaths=…/data`).
- `deploy/marcedit.sudoers` — two NOPASSWD rules: the marcedit
  account can run `systemctl restart marcedit-web`, and the dev
  human can `sudo -iu marcedit` to run the deploy script.
- `deploy/libtools2-marcedit.conf.snippet` — copy-paste Apache
  block for ITS to add to the existing `libtools2.smith.edu`
  vhost. Includes the `<Location /marcedit-web>` Shibboleth
  protection, the websocket `RewriteRule` (must precede the HTTP
  proxy), and the `ProxyPass` / `ProxyPassReverse` pair.
- `.env.example` — template for the env vars systemd reads via
  `EnvironmentFile=` (`MARCEDIT_WEB_PROD`, `MARCEDIT_WEB_ADMINS`,
  etc.).

### Docs
- `docs/its-setup.md` — ITS-facing brief: the four one-time
  root operations needed on libtools2 (useradd, sudoers,
  systemd unit, Apache `<Location>` edit), what to copy from
  the `deploy/` folder, and a verification checklist.
- `docs/deployment.md` — rewrite to drop the Docker/nginx
  sections and become the canonical operator reference for the
  native-venv setup at `libtools2.smith.edu/marcedit-web`.
- `README.md` — update local-dev steps from
  `docker compose up` to `python3.9 -m venv .venv && pip
  install -e .[dev] && streamlit run marcedit_web/App.py`.

### To delete (after Phase 3 succeeds)
- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml`
- `docker-compose.pull.yml`

## Success Criteria

1. Pushing to a feature branch triggers `pytest` on Python 3.9 in
   GitHub Actions; failures block the PR via branch protection.
2. `docker-publish.yml` is gone; GHCR no longer receives new
   images.
3. ITS completes the four one-time root operations on libtools2
   following `docs/its-setup.md` end-to-end with no follow-up
   questions to the dev team.
4. `https://libtools2.smith.edu/marcedit-web/` loads behind
   Shibboleth, the cataloger sees their eppn in the sidebar (not
   "anonymous"), and `id` inside the streamlit process reports
   the `marcedit` system user.
5. `sudo -iu marcedit bash scripts/deploy.sh` cleanly updates the
   running app: pulls main, refreshes the venv, restarts the
   service, and the smoke-test healthcheck passes within 30s.
6. The deployment passes the smoke-test list in `docs/deployment.md`
   (Shib redirect, sidebar identity, marcedit-user process, audit
   log writes, anonymous-bypass refusal).
7. Existing test suite (`pytest`) still passes locally without
   Docker, using only a `python3.9 -m venv` + `pip install -e .[dev]`
   workflow.

## Notes / constraints

- Container runtimes (Docker AND Podman) are off the table per ITS
  policy on libtools2. Native venv only.
- Python 3.9 is already installed on libtools2; no `dnf module
  install python39` ask required.
- Reuses the existing libtools2 TLS cert and Shibboleth SP entity;
  no new IdP registration.
- The dedicated `marcedit` system user (uid/gid TBD by useradd
  defaults) is the service account; the Dockerfile's hardening
  (TASK-029) is replicated at the systemd unit layer rather than
  via a container.
- App code is **not** touched by this ticket. The existing SQLite
  layer (TASK-049/050/051) ships as-is; future Postgres migration
  is a separate ticket if/when motivated.

## Design spec

See `docs/superpowers/specs/2026-06-01-cicd-native-deploy-design.md`
for the full design that produced this scope.
