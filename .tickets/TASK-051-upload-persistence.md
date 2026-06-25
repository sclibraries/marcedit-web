# TASK-051 — Upload persistence across refresh (OAuth users)

**Status:** Completed
**Stage:** Third of three persistence tickets (049 → 050 → 051).

## Title

When a signed-in cataloger uploads a ``.mrc`` and then refreshes
the browser, the loaded batch currently disappears because
``st.session_state`` is wiped on every hard refresh. The file on
disk in ``/tmp/marcedit-web-records-*`` lives on, but nothing
re-attaches it.

Fix: for OAuth-authenticated users, persist the upload to a stable
path under ``data/uploads/<slug>/upload.mrc`` and track it in a new
SQL ``uploads`` table. On session init, if the user has an active
upload row and the file still exists, reattach it into
``st.session_state["store"]``.

Anonymous (not-signed-in) users get the current behavior — refresh
loses the upload. "Sign in to keep your work" is the natural prompt.

## Scope

- **Schema bump v2 → v3** in ``lib/db.py``:
  ```sql
  CREATE TABLE uploads (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      user_email    TEXT    NOT NULL,
      filename      TEXT    NOT NULL,          -- original filename
      file_path     TEXT    NOT NULL,          -- on-disk persisted path
      record_count  INTEGER NOT NULL,
      file_bytes    INTEGER NOT NULL,
      uploaded_at   TEXT    NOT NULL,          -- ISO-8601 UTC
      active        INTEGER NOT NULL DEFAULT 1 -- 1 = current upload
  );
  CREATE INDEX idx_uploads_user_active ON uploads(user_email, active);
  ```
- **New `marcedit_web/lib/upload_persistence.py`:**
  * ``persisted_upload_dir(user) -> Path`` — returns
    ``data/uploads/<safe_user_slug>/`` (created on demand). Reuses
    ``task_storage.safe_user_slug`` so the slug rules match the
    existing per-user filesystem path.
  * ``record_upload(user, filename, file_path, record_count,
    file_bytes)`` — clear any prior active row for ``user``, insert
    the new active row. Idempotent — re-recording the same row is
    cheap.
  * ``get_active_upload(user) -> dict | None``
  * ``clear_active_upload(user)`` — flips ``active`` to 0 and
    unlinks the on-disk file. Used when the user clears the upload.
  * Sentinel handling: ``user == ANONYMOUS`` or empty short-circuits
    everything to no-op. Persistence is OAuth/Shibboleth-only.
- **`marcedit_web/lib/session.py`:**
  * ``handle_upload``: after the RecordStore is built, write the
    raw bytes to ``persisted_upload_dir(user)/upload.mrc`` (replaces
    any existing file), then ``record_upload(...)``. Anonymous users
    keep using the per-session tmp dir.
  * Add ``restore_active_upload()``: called from ``init()``. If
    ``session_state["store"]`` is None AND the user isn't
    anonymous AND ``get_active_upload(user)`` returns a row whose
    ``file_path`` still exists, build a RecordStore from it and
    install it. Emit a one-time ``upload-restored`` audit event.
  * Handle the upload-clear case (user uploads ``None`` to reset):
    call ``clear_active_upload(user)`` so the next refresh doesn't
    rehydrate the just-cleared file.
- **New audit kinds:** ``upload-restored`` (refresh rehydrate).
- **Tests** (``tests/test_upload_persistence.py``):
  * CRUD: record/get/clear round-trip.
  * Anonymous user → no-op (no row inserted).
  * Recording a new upload supersedes the prior active row (only
    one ``active=1`` per user at a time).
  * File-on-disk gone but DB row present → ``get_active_upload``
    still returns the row (we don't pre-validate; the caller does).
  * ``clear_active_upload`` deletes both the on-disk file and the
    active flag.
- **Tests** (``tests/test_session_restore.py``):
  * ``handle_upload`` for an OAuth user inserts an ``uploads`` row
    and writes the persisted file.
  * ``restore_active_upload`` reattaches a previously-uploaded
    store into a fresh ``session_state["store"]``.
  * ``restore_active_upload`` does nothing for anonymous.
  * Missing-file recovery: row in DB, file gone → restore returns
    None and clears the row.
- **``docs/deployment.md``:** new "Persisted uploads" subsection
  noting the ``data/uploads/`` mount and refresh-resume behavior.
  Add ``data/uploads/`` to the .gitignore patterns.

## Out of scope

- Multi-upload history (showing past uploads to re-attach).
  Today only the "active" upload survives; a previous upload is
  overwritten when a new one arrives.
- Persistence for anonymous users via session cookies. Decided
  against in the earlier design questions; "sign in to keep your
  work" is the answer.
- Cross-user upload sharing. Uploads are private to the owner.

## Success Criteria

1. Signed-in cataloger uploads ``foo.mrc``, then refreshes the
   browser tab → the Home page still shows ``foo.mrc loaded``
   without re-uploading.
2. ``data/marcedit.db`` has one row in ``uploads`` per signed-in
   user's most-recent upload; ``active=1``.
3. Re-uploading replaces the active row (and on-disk file) atomically.
4. Anonymous user uploads still work; refresh loses the upload
   (no DB row, no persisted file).
5. ``MARCEDIT_WEB_PROD=1`` and unauthenticated → still blocked by
   ``enforce_auth`` before any upload action runs.
6. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose exec marcedit-web sqlite3 /app/data/marcedit.db \
    "SELECT user_email, filename, record_count, active FROM uploads"
```
