# TASK-049 — SQLite foundation + audit-event mirror

**Status:** Completed
**Stage:** First of three persistence tickets (049 → 050 → 051).

## Title

Stand up a per-deployment SQLite database that all three
persistence features (this ticket, tasks-in-SQL, upload
persistence) share. Wire the existing JSONL audit log to also
write to a new ``audit_events`` SQL table — operators keep their
``tail``-able file; analysts gain a queryable index.

This ticket deliberately does NOT migrate tasks or uploads.
Those land in TASK-050 / TASK-051.

## Scope

- **New `marcedit_web/lib/db.py`**:
  * ``DB_PATH = Path(os.environ.get("MARCEDIT_WEB_DB_PATH",
    "data/marcedit.db"))``. The default lives under the same
    ``data/`` mount that's already writable by uid 10001.
  * ``connect() -> sqlite3.Connection`` context manager:
    ``with db.connect() as conn: ...``. Each call opens a fresh
    connection (Streamlit threads safely this way), sets
    ``row_factory = sqlite3.Row``, enables foreign keys, and
    closes on exit. Commits on normal exit; rolls back on
    exception.
  * ``init_schema() -> None``: idempotent ``CREATE TABLE IF NOT
    EXISTS`` for the tables this ticket owns. Called once at
    process start. WAL mode is enabled here for write
    concurrency.
  * ``_schema_version`` table for future migrations. This ticket
    sets it to 1.
- **Audit table:**
  ```sql
  CREATE TABLE audit_events (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      ts           TEXT    NOT NULL,           -- ISO-8601 UTC
      user_email   TEXT    NOT NULL,           -- ANONYMOUS sentinel allowed
      kind         TEXT    NOT NULL,
      payload_json TEXT    NOT NULL
  );
  CREATE INDEX idx_audit_user_ts ON audit_events(user_email, ts);
  CREATE INDEX idx_audit_kind_ts ON audit_events(kind, ts);
  ```
- **`marcedit_web/lib/audit.py`** — modify ``audit_event(...)`` to:
  1. Keep its existing JSONL write (operator continuity).
  2. ALSO insert one row into ``audit_events`` with the same
     timestamp, kind, user, and the remaining fields serialized
     as ``payload_json``.
  3. SQL write is wrapped in its own try/except — a DB failure
     must NOT block the JSONL write or the calling action.
- **App.py entrypoint** — call ``db.init_schema()`` once at module
  import time. Cheap (idempotent) so no flag needed.
- **`.gitignore`** — verify ``data/`` already ignores the db file
  (yes, the existing ``data/audit/`` + ``data/tasks/...`` patterns
  cover dev; the db file at ``data/marcedit.db`` lives alongside
  them, and operators have ``data/`` as a mount). Add an explicit
  pattern for ``data/*.db`` to be safe.
- **Tests** (`tests/test_db.py`):
  * ``connect()`` produces a usable connection; commits on
    normal exit; rolls back on exception.
  * ``init_schema()`` is idempotent (call twice, no error).
  * After ``init_schema()``, ``audit_events`` table + indexes
    exist; schema_version row is set to 1.
- **Tests** (`tests/test_audit.py`):
  * Calling ``audit_event(kind, user=..., **fields)`` produces a
    JSONL line AND a matching ``audit_events`` row.
  * Two events in quick succession yield two rows with the same
    timestamp ordering.
  * A simulated SQL failure (point ``MARCEDIT_WEB_DB_PATH`` at an
    unwritable location) still produces the JSONL line.
- **Dep:** none new. ``sqlite3`` is stdlib.
- **docs/deployment.md** — add a "Database" subsection: file
  location, env-var override, backup story (copy the file), the
  fact that audit dual-writes for now and JSONL will go away in a
  future ticket once SQL is proven.

## Out of scope

- Task storage in SQL — TASK-050.
- Upload persistence — TASK-051.
- A query / search UI for the audit table — operators can sqlite3
  the file directly for now.
- Postgres support — SQLite is the deliberate choice; adding a
  driver abstraction now is speculative.
- Migrating historical JSONL events into the new table — this
  ticket only forward-writes. Historical JSONL files remain on
  disk and are still tail-able.

## Success Criteria

1. ``marcedit_web/lib/db.py`` exists with the three exports above.
2. After ``init_schema()``, ``sqlite3 data/marcedit.db
   ".schema"`` shows ``audit_events`` with both indexes and
   ``_schema_version`` set to 1.
3. Every existing audit emit-site continues to produce a JSONL
   line AND now also produces a row in ``audit_events`` with the
   same ``ts`` / ``kind`` / ``user``.
4. A deliberately broken DB (read-only path) does NOT throw from
   the user's action; the JSONL line is still produced; a warning
   lands in the logger.
5. ``pytest -q`` stays green; the new tests cover the assertions
   above.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose exec marcedit-web sqlite3 /app/data/marcedit.db ".schema audit_events"
```
