# Task 4 Report — Atomic immutable version adoption

Ticket: [TASK-151](../../.tickets/TASK-151-job-file-work-items-implementation.md)

## Status

Completed. The single job-file mutation gateway validates and stages candidate
MARC bytes, rechecks current editor access plus the holder's unexpired checkout
and exact opened version inside one write transaction, creates an immutable
child version, compare-and-swaps the current pointer, resets release state, and
supersedes draft/ready exports. The session wrapper reopens the adopted current
version and clears stale previews through `open_job_file`.

## Files

- `marcedit_web/lib/job_files.py`
- `marcedit_web/lib/session.py`
- `tests/test_job_file_mutations.py` (new)

`tests/test_job_files.py` required no Task 4 change; its existing archive-only
retention tests remained in the focused regression selection.

## TDD evidence

### Initial RED

Command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q tests/test_job_files.py tests/test_job_file_mutations.py
```

Result: **8 failed, 11 passed**. Every failure was the expected missing API:
`job_files.adopt_candidate` or `session.adopt_current_candidate`.

The first host-side `pytest` attempt did not reach tests because the local
environment could not import `marcedit_web`; Docker was used for all meaningful
RED/GREEN and completion evidence.

### Initial GREEN

Same focused command: **19 passed in 0.61s**.

Required storage/session command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q tests/test_job_files.py tests/test_job_file_mutations.py tests/test_record_store.py tests/test_session.py
```

Result: **65 passed in 0.77s**.

### Review-driven RED

Independent review identified cross-filesystem candidate rename, stale access,
and partially malformed candidate gaps. Regression command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q tests/test_job_file_mutations.py
```

Result: **4 failed, 8 passed**, specifically proving:

- direct `/tmp` to durable-root `os.replace` failed with simulated `EXDEV`;
- a valid record followed by malformed bytes was accepted;
- revoked access mutated before the return lookup failed;
- downgraded viewer access was accepted.

### Final GREEN

Required focused storage/session command after fixes: **69 passed in 0.83s**.

Final full-suite command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q
```

Result: **1142 passed in 15.92s**, with no skipped tests reported.

`git diff --check` passed. The Docker image does not contain `ruff` (`exec:
"ruff": executable file not found`), so a separate lint run was unavailable.

## Self-review

- Candidate indexing and malformed/empty rejection happen before database work.
- Candidates are copied to a unique pending path beneath the durable job-files
  root before the atomic rename, avoiding cross-device rename failures.
- Current owner/editor access, non-archived state, checkout holder/expiry, and
  exact opened version are all checked after `BEGIN IMMEDIATE`.
- On failure after rename, target bytes move back to staging before SQLite
  rollback; outer cleanup removes the original, staging, and target paths.
- The current-pointer update is an explicit compare-and-swap and is covered by
  a forced post-rename pointer failure test.
- Prior immutable bytes and approval history remain intact; the new version is
  unapproved, file status returns to `in_progress`, and draft/ready exports are
  superseded. Loaded exports are retained.
- No deletion API or editor/batch call-site conversion was added.

## Concerns

- No unresolved Critical or Important review findings.
- Candidate staging temporarily requires space for one additional copy under
  the durable root. This is required for a same-filesystem atomic rename and
  remains disk-backed/bounded-memory via `shutil.copyfile`.
- Standalone lint tooling is absent from the supplied Docker image; full pytest
  and `git diff --check` are clean.
