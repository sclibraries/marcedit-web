# marcedit-web

Web-based MARC21 viewer, validator, editor, and diff. Recreates MarcEdit's
generic editing features as a Streamlit app, deployed at
https://libtools2.smith.edu/marcedit-web/ behind Apache + mod_shib on
RHEL 8.10.

See `docs/application-overview.md` for the current architecture and
recommended speed, consistency, and hardening improvements.

## Local development

Prerequisite: Python 3.9 (pinned in `pyproject.toml`). On macOS:
`brew install python@3.9`. On Linux: use your distro's Python 3.9
package; on RHEL: `dnf module install python39`.

```sh
git clone <repo URL>
cd marcedit-web

python3.9 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"

streamlit run marcedit_web/App.py
```

The app loads at `http://localhost:8501/`. For Google OAuth in local
dev, copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and follow the setup notes there.

Run the test suite:

```sh
pytest
```

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

- `docs/deployment.md` — canonical operator reference for the
  native-Python deploy at `libtools2.smith.edu/marcedit-web`:
  environment variables, identity model, service management,
  audit log, and smoke tests.
- `docs/its-setup.md` — one-page brief for ITS covering the four
  one-time root operations needed to onboard a new host.
- `.github/workflows/test.yml` runs `pytest` on Python 3.9 against
  every push and PR; required on `main`.

## Tickets

Every code change traces to a ticket under `.tickets/TASK-NNN-<slug>.md`
(see `CLAUDE.md` Rule 13). Bootstrap stage = `TASK-001-bootstrap.md`.
