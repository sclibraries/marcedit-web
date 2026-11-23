# ADR 0001: React frontend and Flask API replace Streamlit

Date: 2026-11-23 · Status: accepted (owner) · Applies when the rewrite is built; `ARCHITECTURE.md` still
describes `main`.

**Context.** Streamlit reruns make navigation, loading feedback and large batches slow. TASK-252 advised
staying on Streamlit in September; the owner has since chosen to replace it. The usual backend for new
apps here is Yii (PHP), but the engine (open-marc-tasks) and the code being kept are Python. Production
is Python 3.9 without containers.

**Decision.** React + TypeScript (Tailwind, shadcn/ui) in `frontend/`; a thin Flask 3.1 API in
`marcedit_web/api/` served by waitress; existing `lib/` logic, SQLite and `data/` kept. One switchover,
after rehearsals on a separate copy.

**Why Flask.** Current Flask supports 3.9; the last FastAPI for 3.9 is 0.128.8 and Starlette's is 0.49.3,
both frozen. The TASK-198 FastAPI prototype is mined, not merged.

**Costs.** No built-in request models or OpenAPI: contracts are JSON Schemas with generated TypeScript
types. Nothing reaches catalogers until switchover, so they test on a second service.
