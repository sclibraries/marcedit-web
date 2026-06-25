# TASK-050 — Tasks in SQL with private/shared visibility

**Status:** Completed
**Stage:** Second of three persistence tickets (049 → 050 → 051).

## Title

Move user tasks from the filesystem (``data/tasks/users/<slug>/*.py``
+ ``data/tasks/shared/*.py``) into a SQLite ``tasks`` table with a
private/shared visibility flag. The Python loader still needs files
on disk to import; we materialize each user's visible tasks to a
per-session temp directory at render time.

## Scope

- **Schema bump v1 → v2** in ``lib/db.py``:
  ```sql
  CREATE TABLE tasks (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_email   TEXT NOT NULL,
      name          TEXT NOT NULL,
      description   TEXT NOT NULL DEFAULT '',
      body          TEXT NOT NULL,
      extra_imports TEXT NOT NULL DEFAULT '',
      visibility    TEXT NOT NULL DEFAULT 'private'
                    CHECK(visibility IN ('private','shared')),
      created_at    TEXT NOT NULL,
      updated_at    TEXT NOT NULL,
      UNIQUE(owner_email, name)
  );
  CREATE INDEX idx_tasks_owner ON tasks(owner_email);
  CREATE INDEX idx_tasks_visibility ON tasks(visibility);
  ```
- **File → SQL migration** (one-shot, idempotent, runs inside
  ``init_schema()`` when stored schema version is < 2):
  * Walk ``data/tasks/users/<slug>/*.py`` — owner is the slug
    (best-effort reverse of ``safe_user_slug``; we keep the slug
    as the literal owner_email since reversing isn't lossless,
    but emails round-trip cleanly because the slug regex permits
    ``@`` and ``.``).
  * Walk ``data/tasks/shared/*.py`` — owner is the sentinel
    ``__shared__``, visibility is ``shared``.
  * Use ``INSERT OR IGNORE`` so re-runs are safe; bump schema
    version to 2 only after migration completes.
  * Leave the original files on disk as a backup. A future
    ticket can delete them after operators sign off.
- **New `marcedit_web/lib/task_db.py`** — CRUD + materialization:
  * ``save_task(owner, name, description, body, extra_imports=[],
    visibility="private")`` — upsert by (owner, name); ``updated_at``
    bumped.
  * ``delete_task(owner, name) -> bool``
  * ``set_visibility(owner, name, visibility)``
  * ``list_visible_tasks(user) -> list[dict]`` — user's own tasks
    + every ``visibility='shared'`` row.
  * ``materialize_to_dir(user, target_dir)`` — writes each visible
    task as a ``.py`` file via the existing
    ``editor.serialize_user_task``. Returns count.
- **`marcedit_web/render/tasks.py`** rewrite:
  * Replace ``task_storage.user_tasks_dir(user)`` with a
    per-session tmp dir under ``/tmp/marcedit-web-tasks-<session>/``.
  * Re-materialize visible tasks on every Tasks-page render
    (cheap; the importer's mtime guard prevents reparsing).
  * Save / delete callbacks write to SQL via ``task_db``, then
    re-materialize.
  * Replace the existing "Yours / Shared / Registered" metric
    bar with SQL-backed counts.
  * Add a Visibility toggle in the editor (radio: Private /
    Shared) so authors control sharing per task.
- **Legacy `task_storage.py`** stays for tests + the migration's
  filesystem walk. The render layer no longer calls
  ``user_tasks_dir`` / ``shared_tasks_dir`` for storage; only
  the migration reads them.
- **Tests:**
  * ``tests/test_task_db.py``: CRUD round-trip, visibility filter
    (user sees own + shared, not other users' private),
    materialize-to-dir produces parseable files, schema
    constraint enforces visibility values, owner+name uniqueness.
  * ``tests/test_db_migration.py``: file → SQL migration is
    idempotent + correct (users + shared dirs land in the right
    rows; schema_version bumps).
  * Existing ``tests/test_task_storage.py`` keeps working
    (those tests exercise the filesystem helpers, which still
    exist for the migration).
- **`docs/deployment.md`**: note tasks are now SQL-backed; on
  first boot post-deploy, existing on-disk tasks migrate
  automatically; the disk files are a backup until cleared.

## Out of scope

- Per-user grants (Alice shares with Bob but not Carol).
  TASK-050-followup if catalogers actually ask.
- Deleting the on-disk ``data/tasks/users/`` and ``shared/``
  files post-migration. Keep as a manual operator step until
  SQL is proven.
- An admin UI for editing tasks owned by ``__shared__``.
  Operators can SQL-edit those rows directly until a UI is needed.
- Upload persistence — TASK-051.

## Success Criteria

1. ``data/marcedit.db`` after first post-deploy boot contains
   one ``tasks`` row per pre-existing on-disk task with the
   correct owner / visibility.
2. ``_schema_version`` is bumped to 2.
3. Tasks page shows the cataloger's own tasks AND all tasks
   marked ``shared``; a private task created by Bob is not
   visible to Alice.
4. Editing visibility on a task immediately changes who sees it.
5. Saving a task writes to SQL; the next render's materialization
   produces a file the importer can load, and the task appears
   in the Existing Tasks list.
6. ``pytest -q`` stays green; new tests cover the assertions
   above.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose exec marcedit-web sqlite3 /app/data/marcedit.db \
    "SELECT owner_email, name, visibility FROM tasks ORDER BY id"
```
