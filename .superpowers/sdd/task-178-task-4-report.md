# TASK-178 Task 4 implementation report

## Result

- Scope: Task 4 only
- Status: Complete

## Implemented

- Added fail-closed `prepare_task_for_execution(owner, name, audit_user=...)`.
- Returned legacy rows unchanged without loading, validating, compiling, or
  fingerprinting a native definition.
- Parsed, validated, and compiled native definitions before opening the
  migration write transaction.
- Compared current-fingerprint body and newline-joined import snapshots byte
  for byte, raising a column-specific `NativeTaskIntegrityError` without
  repairing mismatches.
- Regenerated stale snapshots with one CAS update matching task ID, revision,
  and the exact stored definition JSON bytes.
- Incremented revision and updated timestamp atomically with migrated body,
  imports, and fingerprint.
- Raised `NativeTaskCompatibilityError` on missing rows, stored-definition
  validation failures, compiler contract/compilation failures, and CAS races.
  Wrapped native validation/contract/compile failures with their original
  message and exception chaining.
- Emitted `native-task-compiler-migrated` only after the migration transaction
  committed, with audit user, owner, task name, and old/new fingerprints.
- Verified or migrated each native row before serializing its materialized
  Python file while preserving the legacy row path, stale-file cleanup, and
  unchanged-content mtime behavior.
- Preserved the reviewed legacy/native conversion concurrency guard from
  Task 3 unchanged.

## TDD evidence

### RED

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest \
    tests/test_native_task_storage.py \
    tests/test_task_db.py \
    tests/test_audit.py -q
```

Result before production implementation: **10 failed, 39 passed, 0 skipped**.
The failures identified the missing preparation API/error types and absent
materialization verification. The stale-materialization fixture initially
used a private owner row for a different viewer; it was corrected to shared
visibility before GREEN so the test exercises migration rather than
visibility filtering.

### GREEN

The same three-module command after implementation produced **49 passed,
0 failed, 0 skipped**. A compiler-contract failure case was then added to the
existing byte-preservation parameterization.

### Audit timing

The stale-fingerprint migration test replaces `audit.audit_event` with a
collector that re-reads the task from a separate database connection. It
requires the current fingerprint to be visible before accepting the event,
proving the audit call occurs after commit. It also requires the exact event
kind and payload, including the viewer as `user` and both fingerprints.

### Byte preservation and CAS

- Same-fingerprint tampering is parameterized over `body` and
  `extra_imports`; each mismatch raises the column-specific integrity error
  and leaves the complete row unchanged.
- Invalid stored JSON and both compilation and compiler-contract failures
  leave the complete row byte-identical.
- A deterministic compile-time concurrent update increments the revision and
  changes the body. The migration CAS affects zero rows, raises the exact
  compatibility error, and preserves the concurrent body, stale fingerprint,
  and incremented revision.
- Materialization tests require valid native output to parse, stale output to
  migrate before serialization, and an integrity failure to create no file
  for the native task.

## Final verification

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest \
    tests/test_native_tasks.py \
    tests/test_native_task_contract.py \
    tests/test_native_task_schema_migration.py \
    tests/test_native_task_storage.py \
    tests/test_task_db.py \
    tests/test_audit.py -q
```

Pre-review result: **70 passed, 0 failed, 0 skipped in 1.78s**.
Final post-review result: **70 passed, 0 failed, 0 skipped in 1.99s**.

Additional check: `git diff --check` passed.

## Independent review

The read-only Task 4 review found no Critical, Important, or Minor issues and
assessed the implementation ready to merge. It specifically confirmed the
exact CAS predicate, post-commit audit ordering, fail-closed integrity path,
error wrapping, legacy bypass, materialization ordering, and focused test
coverage.

## Concerns

None. No Task 5, UI, deployment, authorization, preview reporting, schema, or
unrelated refactor work was performed.
