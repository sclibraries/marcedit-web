Title: Restore shared-job file attachment on production SQLite

Scope:
- Reproduce the production `sqlite3.OperationalError` raised by
  `job_files.attach_file()` near `RETURNING`.
- Make every runtime job-file identity insert compatible with the supported
  production SQLite version without weakening version allocation or
  concurrency safety.
- Keep changes limited to job-file persistence and its intent-focused tests.

Success Criteria:
- A shared-job file can be attached on the minimum supported SQLite version.
- Existing uploads with retained artifacts migrate idempotently into visible
  job files on the minimum supported SQLite version.
- Created attachment, export, and immutable-version identities are returned
  deterministically on the same transaction connection.
- Failure remains atomic and concurrent attachment cannot select another
  transaction's row.
- Focused and complete applicable tests pass with every skip reported, and
  review has no unresolved Critical or Important findings.

Status: In-Progress
