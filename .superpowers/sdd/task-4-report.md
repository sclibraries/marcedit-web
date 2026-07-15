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

## Formal review follow-up — uncertain commit and structural validation

The controller's formal review found two additional gaps:

1. A transaction-exit exception could occur after SQLite had durably committed.
   Unconditional outer cleanup would then unlink the adopted target while the
   committed current pointer still referenced it.
2. MARC framing alone could count a plausible-length record whose leader or
   directory could not be parsed by pymarc.

### Follow-up RED

Command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q tests/test_job_file_mutations.py
```

Result: **2 failed, 13 passed in 0.57s**.

- A commit persisted and then raised; the gateway propagated the raw exception
  and deleted the committed target.
- A correctly framed record with an invalid `99999` MARC base address was
  adopted because it had one indexed frame and no truncated suffix.

The paired commit-before-persistence regression passed under the old code,
confirming that ordinary rollback cleanup was already correct and isolating the
bug to uncertain transaction-exit outcomes.

### Follow-up GREEN

Mutation gateway command after the fix: **15 passed in 0.47s**.

Required focused/storage/session command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q tests/test_job_files.py tests/test_job_file_mutations.py tests/test_record_store.py tests/test_session.py
```

Result: **72 passed in 0.84s**.

Fresh full-suite command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q
```

Result: **1145 passed in 16.17s**, with no skipped tests reported.

`git diff --check` passed.

### Follow-up self-review

- The normal operation-failure path still restores target bytes to staging
  before the database context rolls back.
- Only a failure escaping transaction context exit while the target is still
  adopted triggers a fresh durable-state query.
- If version row and current pointer committed with the exact target path, the
  target is retained and `JobFileError` explicitly reports that adoption
  succeeded but transaction confirmation failed.
- If the durable query shows no committed adoption, target bytes return to
  staging and all candidate artifacts are removed.
- If the durable query itself fails, target bytes are conservatively retained;
  this may leave an orphan but cannot create a committed pointer to missing
  bytes.
- Candidate validation now iterates every indexed record through pymarc and
  compares successfully parsed records to the frame count. Iteration reads one
  record at a time from disk and retains no full-file or record-list copy.
- Cross-filesystem staging, checkout/access/version checks, prior immutable
  bytes, export supersession, and archive-only behavior are unchanged.

No unresolved Critical or Important formal-review findings remain in this
follow-up implementation.

## Formal review follow-up — historical-version reconciliation race

The next formal review identified that durable version existence was still
coupled to `current_version_id`. A committed v2 could be advanced to historical
state by a valid v3 adoption before the uncertain-commit reconciliation query;
the old helper then classified v2 as uncommitted and deleted bytes still
referenced by v2's row and v3's parent chain.

### Race RED

The public regression commits v2, performs a second public `adopt_candidate`
that creates v3 from v2 before reconciliation, then raises the original commit
confirmation error.

Command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q tests/test_job_file_mutations.py
```

Result: **1 failed, 15 passed in 0.58s**. The v2 database row and v3 parent
reference remained, but `v000002.mrc` had been deleted.

### Race GREEN

Mutation command after tightening the expected public error type:
**16 passed in 0.52s**.

Required focused/storage/session command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q tests/test_job_files.py tests/test_job_file_mutations.py tests/test_record_store.py tests/test_session.py
```

Result: **73 passed in 0.95s**.

Fresh full-suite command:

```text
docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q
```

Result: **1146 passed in 16.37s**, with no skipped tests reported.

`git diff --check` passed.

### Race self-review

- Reconciliation now queries the exact `job_file_versions.id`,
  `job_file_id`, and `file_path`; any matching immutable row preserves its
  target bytes regardless of whether it remains current.
- The deterministic regression verifies the complete chain: v1 bytes remain,
  v2 historical bytes remain, v3 remains current, and v3's parent is v2.
- The existing commit-before-persistence regression remains green and still
  proves that an absent version row permits staging/target cleanup.
- No checkout, access, CAS, staging, validation, export, session, or archive
  behavior changed.

No unresolved Critical or Important findings remain from this race fix.
