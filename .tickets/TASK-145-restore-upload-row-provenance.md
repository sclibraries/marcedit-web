Title: Snapshot restore creates a new upload row per restore

Scope:
- Pre-existing behavior surfaced by the TASK-143 History page:
  "Restore pre-change version" calls
  `session.replace_current_store_from_bytes`, which records a NEW
  uploads row with the same filename. Consequences:
  - The History recent-files fallback grows one row per restore.
  - The timeline's origin entry (`uploads[-1]` matching the current
    filename) shows the restore's timestamp and serves the restored
    bytes as "Download original" instead of the true original upload.
- Decide and implement: mark restore-created rows (e.g. a source
  column) and exclude them from the origin lookup and recent-files
  list, or reuse the existing row instead of inserting.

Success Criteria:
- After N restores, the recent-files list shows the file once.
- The timeline origin entry always reflects the true original upload
  (timestamp and bytes).
- Migration handled if the uploads schema changes.

Status: Todo
