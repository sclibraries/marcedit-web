# TASK-012 — Task persistence (per-user filesystem)

**Status:** Completed
**Stage:** 12 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md` v2)

## Title

Move task storage off `tempfile.mkdtemp(...)` (lost on session end) onto
a per-user filesystem layout under `data/tasks/`, with a shared
sibling directory anyone can read.

## Why

v1 stored tasks in a per-session temp dir, which the user surfaced as
the second top problem: "Tasks do need to persist in memory after they
have been uploaded. We do not want users to continuously upload tasks."
Catalogers were re-uploading the same `.tasksfile` on every visit.

## Scope

- `marcedit_web/lib/task_storage.py` (new):
  * `user_tasks_dir(user: str) -> Path`
  * `shared_tasks_dir() -> Path`
  * `visible_task_dirs(user: str) -> list[Path]` — shared first,
    user second, so a name collision means the user's wins.
  * `safe_user_slug(user: str) -> str` — restricts to
    `[A-Za-z0-9_.@-]`; everything else maps to `_`. Prevents path
    traversal via an evil eppn.
  * `tasks_root() -> Path` — `<repo>/data/tasks/` by default,
    overridable via the `MARCEDIT_WEB_TASKS_ROOT` env var so tests
    can point it at `tmp_path`.

- `pages/4_Tasks.py` rewrite of the `_session_tasks_dir()` block:
  * Compute `user = session.current_store()`-irrelevant — read from
    `st.session_state["user"]` directly.
  * Save target: `user_tasks_dir(user)`.
  * Loader: `tasks.load_user_tasks(...)` once per dir in
    `visible_task_dirs(user)` (shared then user). User-named tasks
    shadow shared ones via the existing `force_reload=True` semantics.
  * "Clear all tasks" only deletes from the USER dir; a separate
    explicit step would be required to delete from `shared/`.
  * New "Share with library" button per task (out of v1 ticket scope
    for time — landed only if it fits).

- `docker-compose.yml`: mount `./data` read-write (currently `:ro`).

- `tests/test_task_storage.py`:
  * Round-trip via `editor.save_user_task(user_tasks_dir("eppn@x"), ...)` then `tasks.load_user_tasks(...)`.
  * Shared / user shadowing: same name in both, user wins.
  * Slug safety: `safe_user_slug("../../etc/passwd")` doesn't
    escape `data/tasks/users/`.

## Out of scope

- The "Share to library" copy button (nice-to-have; can ship in a
  v2.5 ticket).
- Deleting shared tasks from the UI (operational-only for now).

## Success Criteria

1. Tasks survive `docker compose restart` — Playwright creates a
   task, restarts the stack, the task is still listed.
2. The user dir slug is filesystem-safe; an attacker eppn does not
   escape `data/tasks/users/`.
3. Shared and user task name collision resolves in the user's favor.
4. `pytest -q` stays green.
5. Tasks dir is mounted read-write in `docker-compose.yml`.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → Tasks → create "noop" → docker compose restart →
# revisit Tasks page → confirm "noop" still listed.
docker compose down
```

## Verification result (2026-05-24)

- `marcedit_web/lib/task_storage.py` (new, 100 LOC) exposes
  `tasks_root()`, `safe_user_slug()`, `user_tasks_dir()`,
  `shared_tasks_dir()`, `visible_task_dirs()`. The `..` traversal
  attack is closed via a second pass that replaces `..` runs even
  though `.` is otherwise allowed (for email-style usernames).
- `pages/4_Tasks.py` no longer uses `tempfile.mkdtemp(...)`. Tasks
  load from `shared/` then user dir on every render; saves go to
  the user dir. Sidebar now reads "N yours · N shared · N
  registered total" and "Clear my tasks" only deletes from the
  user dir.
- `docker-compose.yml` mounts `./data` read-write (was `:ro`).
- `.gitignore` excludes `data/tasks/users/` and `data/tasks/shared/`
  so user-saved tasks don't accidentally land in version control.
- Tests: 12 new (`tests/test_task_storage.py`) covering slug
  safety (incl. `../../etc/passwd`), env-var override, dir
  creation, visible-dir ordering, round-trip via
  `editor.save_user_task` + `tasks.load_user_tasks`, and the
  shared-vs-user shadowing contract. Total **196 passed in 0.41s**
  under Python 3.9-slim.
- Playwright smoke: Home → Tasks → "+ New task" → name =
  `persist-demo`, description = "Survives docker restart" → Save →
  task file lands at
  `data/tasks/users/anonymous/persist_demo.py` (415 bytes, real
  Python content) → `docker compose restart` → revisit Tasks
  page → sidebar shows "1 yours · 0 shared · 1 registered total",
  Existing tasks section lists `persist-demo` with the
  description, Edit + Delete buttons visible. The task survived
  the container restart.

All five success criteria satisfied.
