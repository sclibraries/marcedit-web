# TASK-110: Persist record edits across refresh

## Title

Persist single-record editor saves to the active upload file.

## Scope

- Ensure a saved cataloger edit updates the disk-backed MARC file used by upload
  restoration.
- Preserve existing save validation: invalid single-record edits must still be
  blocked before persistence.
- Keep the change focused on durability; export controls, changed-line
  highlighting, and stricter load-readiness warnings are follow-on tickets.

## Success Criteria

- A record changed through the single-record editor survives a page refresh.
- A fresh `RecordStore.from_path(...)` sees the edited record after save.
- Existing snapshot/audit behavior remains intact.
- Focused tests pass.

## Status

Completed

## Verification

- `docker compose run --rm marcedit-web pytest tests/test_record_store.py tests/test_session_restore.py tests/test_session.py`
- `docker compose run --rm marcedit-web pytest -ra`
