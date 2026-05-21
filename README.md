# marcedit-web

Web-based MARC21 viewer, validator, editor, and diff. Recreates MarcEdit's
generic editing features as a Streamlit app, deployable on a RedHat 9
server behind a Shibboleth reverse proxy.

This repository is in early bootstrap. See
`/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`
for the full implementation plan.

## Quick start (Docker)

```sh
docker compose up -d --build
open http://localhost:8501
```

Tear down:

```sh
docker compose down
```

## Stack

- Python 3.9 (hard — RedHat ships 3.9)
- Streamlit (multi-page app)
- pymarc
- streamlit-ace (for the MarcEditor page)

## Layout

```
marcedit_web/
  Home.py              # entry — upload + summary
  pages/               # one .py per page (View, Validate, Report, Tasks,
                       # MarcEditor, Diff) — added in later stages
  lib/                 # parsers, validators, helpers
data/
  marc-rules.txt       # single source of truth for validation rules
                       # and click-through tooltip help — added Stage 2+
tests/
.tickets/              # local ticket log (one .md per feature stage)
```

## Tickets

Every code change traces to a ticket under `.tickets/TASK-NNN-<slug>.md`
(see `CLAUDE.md` Rule 13). Bootstrap stage = `TASK-001-bootstrap.md`.
