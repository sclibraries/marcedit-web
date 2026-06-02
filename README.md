# marcedit-web

Web-based MARC21 viewer, validator, editor, and diff. Recreates MarcEdit's
generic editing features as a Streamlit app, deployable on a RedHat 9
server behind a Shibboleth reverse proxy.

See `docs/application-overview.md` for the current architecture and
recommended speed, consistency, and hardening improvements.

## Quick start from source

```sh
docker compose up -d --build
open http://localhost:8501
```

Tear down:

```sh
docker compose down
```

## Run a published image

Use this path on a deployment host that should pull an image instead of
building from source:

```sh
export MARCEDIT_WEB_IMAGE=ghcr.io/OWNER/REPO:latest
docker compose -f docker-compose.pull.yml pull
docker compose -f docker-compose.pull.yml up -d
open http://localhost:8501
```

For GHCR, unauthenticated `docker pull` works only when the package is
public. Private packages require `docker login ghcr.io` first.

## Stack

- Python 3.9 (hard — RedHat ships 3.9)
- Streamlit (multi-page app)
- pymarc
- streamlit-ace (for the MarcEditor page)

## Layout

```
marcedit_web/
  App.py               # Streamlit navigation entrypoint
  views/               # thin page scripts registered by App.py
  render/              # Streamlit UI for each workflow
  lib/                 # parsers, validators, transforms, storage helpers
data/
  marc-rules.txt       # single source of truth for validation rules
                       # and click-through tooltip help
tests/
.tickets/              # local ticket log (one .md per feature stage)
```

## Deployment docs

- `docs/deployment.md` covers production environment variables,
  Shibboleth/nginx wiring, container hardening, audit logging, and
  pulled-image deployment.
- `.github/workflows/docker-publish.yml` publishes multi-arch images to
  GHCR as `ghcr.io/<owner>/<repo>` on `main`, version tags, and manual
  dispatch.

## Tickets

Every code change traces to a ticket under `.tickets/TASK-NNN-<slug>.md`
(see `CLAUDE.md` Rule 13). Bootstrap stage = `TASK-001-bootstrap.md`.
