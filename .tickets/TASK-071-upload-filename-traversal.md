# TASK-071 — Sanitize the .task import filename (path traversal)

**Status:** Completed
**Priority:** Tier 0 — Security (urgent)
**Source:** Deep code audit 2026-06-17 — finding S3 (MEDIUM, confirmed)
**Branch:** task-071-upload-traversal (worktree .worktrees/task-071-traversal)

## Title

Stop building a filesystem path from the client-supplied upload filename in the
MarcEdit `.task` archive import.

## Scope

- `render/tasks.py:369-373` builds `tasks_dir / f".__import__{upl.name}"` then
  `write_bytes()` + `unlink()`. `upl.name` is the raw multipart filename and is
  never sanitized, so a `../`-laced filename (sent via curl) escapes the temp
  dir. Bounded today (only `.task`-suffixed, transient writes under `/tmp` or
  `/app/data`) but still an unauthenticated arbitrary-`.task` write/delete.
- Use `tempfile.mkstemp`/`NamedTemporaryFile` in `tasks_dir` or a uuid name; if
  the original name is needed for display, derive it via `Path(upl.name).name`
  plus the existing slug whitelist.
- Wrap write + convert + unlink in `try/finally` so the temp file is always
  removed.

## Success Criteria

1. An upload whose multipart `filename` contains `../` cannot create or delete
   any file outside the intended temp dir (test sends a traversal filename and
   asserts containment).
2. Normal `.task` imports still work end-to-end.
3. The temp file is removed on both success and exception paths.
4. Focused tests and the Docker test suite pass before completion.

## Resolution (2026-06-17)

Replaced the inline `tasks_dir / f".__import__{upl.name}"` construction with two
helpers in `render/tasks.py`: `_archive_scratch_path` (reduces the client name
to a NUL-stripped bare basename, prefixed with a uuid token, so the scratch file
is always a direct child of `tasks_dir`) and `_convert_uploaded_archive` (writes
to that scratch path, converts, and unlinks in a `finally` so cleanup runs on
both success and exception). The uuid prefix is load-bearing for safety, not
just collision-avoidance — it keeps even a basename of `..` a literal child
filename rather than resolving to the parent dir.

Tests (`tests/test_task_import_traversal.py`, 10 cases): malicious filenames
(`..`, absolute, nested `../`, NUL byte) all stay inside `tasks_dir`; the scratch
file is cleaned up on success and on conversion error; a real `.task` zip still
imports end-to-end through the real converter. Verified falsifiable (the old
construction escapes to `/app/data/tasks/etc/...`). Full Docker suite: 701
passed. Independent code review: approve-with-nits; all accepted nits applied
(NUL-strip, load-bearing-prefix comment, return-type annotation, real-zip
happy-path test). `convert_task_archive` uses the path only as a zip source and
for cosmetic error text, so dropping the original filename is behavior-safe.
Note: the loop ran in Docker (host lacks the `streamlit_ace` dependency that
`render/tasks.py` imports). Commit on branch `task-071-upload-traversal`.
