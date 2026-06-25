# TASK-063 — Pass Gemini key through Docker Compose

**Status:** Completed

## Title

Allow Docker Desktop / Docker Compose runs to use `GEMINI_API_KEY`.

## Scope

- Update `docker-compose.yml` so the `marcedit-web` service receives
  `GEMINI_API_KEY` from the host environment or Compose `.env` file.
- Document the variable in `.env.example`.
- Do not commit an actual API key.

## Success Criteria

1. `docker-compose.yml` includes `GEMINI_API_KEY=${GEMINI_API_KEY:-}` in the
   service environment.
2. `.env.example` documents where to put the Gemini key.
3. Focused tests pass.
