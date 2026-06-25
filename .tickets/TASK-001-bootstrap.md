# TASK-001 — Bootstrap Docker dev environment

**Status:** Completed
**Stage:** 1 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Bootstrap the marcedit-web project skeleton so the app boots in Docker on
`http://localhost:8501`. No MARC logic yet — just the scaffolding the
later stages depend on.

## Scope

- `pyproject.toml` (Python 3.9 target, project metadata)
- `requirements.txt` (streamlit, pymarc>=5.1.2,<6, streamlit-ace pinned)
- `Dockerfile` on `python:3.9-slim`
- `docker-compose.yml` (mounts source + data, port 8501, upload-size env)
- `.streamlit/config.toml` (`maxUploadSize=2048`, `headless=true`)
- `marcedit_web/Home.py` placeholder (empty landing page; shows app title
  and the sidebar nav placeholder)
- `marcedit_web/__init__.py`, `marcedit_web/lib/__init__.py`,
  `marcedit_web/pages/__init__.py` (Streamlit auto-discovers `pages/`,
  but the package needs `__init__.py` for `lib/` imports later)
- `README.md` (brief — install + run instructions)
- `.gitignore` (Python, `__pycache__`, the source `.zip` archives,
  `.venv/`, `.tickets/` left tracked)
- `.dockerignore`

Out of scope for this ticket: any lifted code, MARC parsing, validation,
editor — those are Stage 2+.

## Success Criteria

1. `docker compose build` succeeds with no warnings beyond pip's normal
   noise.
2. `docker compose up -d` followed by
   `curl -fsS http://localhost:8501/_stcore/health` returns `ok`.
3. `docker compose logs marcedit-web` shows Streamlit serving on
   `0.0.0.0:8501`.
4. `docker compose down` cleans up cleanly.
5. Initial commit exists with the scaffolded files (NOT including
   `marc-diff.zip` / `marc-processing.zip`).

## Verification command

```sh
docker compose up -d --build
sleep 8
curl -fsS http://localhost:8501/_stcore/health
docker compose logs --no-color marcedit-web | head -40
docker compose down
```

## Verification result (2026-05-21)

- `docker compose build` — green; final layer ~8.6s build.
- `docker compose up -d` — container `marcedit-web` started cleanly.
- `curl -fsS http://localhost:8501/_stcore/health` → `ok`.
- Logs report `URL: http://0.0.0.0:8501` (Streamlit listening).
- Playwright snapshot of `http://localhost:8501/` shows page title
  "marcedit-web", caption, info alert, and sidebar nav placeholder
  all rendering.
- `docker compose down` removed container and network cleanly.

All five success criteria satisfied.
