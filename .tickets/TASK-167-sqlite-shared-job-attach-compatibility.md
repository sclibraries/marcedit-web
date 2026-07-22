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

Status: Completed

Evidence:
- RED command:
  `docker run --rm --network none -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/prod-fixes-task-167-170:/workspace:ro -w /workspace -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest tests/test_job_files.py::test_attach_file_works_without_sqlite_returning tests/test_job_file_migration.py -q`

  Output (exit 1; 2 failed, 12 passed, 0 skipped):

  ```text
  FF............                                                           [100%]
  =================================== FAILURES ===================================
  _______________ test_attach_file_works_without_sqlite_returning ________________

  tests/test_job_files.py:59: in test_attach_file_works_without_sqlite_returning
      attached = attach_fixture(job["id"], tmp_path, "routledge.mrc", b"record")
  tests/test_job_files.py:38: in attach_fixture
      return job_files.attach_file(
  marcedit_web/lib/job_files.py:237: in attach_file
      version = conn.execute(
  tests/test_job_files.py:23: in execute
      raise sqlite3.OperationalError('near "RETURNING": syntax error')
  E   sqlite3.OperationalError: near "RETURNING": syntax error

  ___________ test_existing_upload_migrates_once_to_immutable_version ____________

  tests/test_job_file_migration.py:206: in test_existing_upload_migrates_once_to_immutable_version
      assert first is not None
  E   assert None is not None
  ------------------------------ Captured log call -------------------------------
  WARNING  marcedit_web.job_files:job_files.py:163 migration: skipping upload 1 at /tmp/pytest-of-marcedit/pytest-0/test_existing_upload_migrates_0/legacy.mrc: near "RETURNING": syntax error
  WARNING  marcedit_web.job_files:job_files.py:163 migration: skipping upload 1 at /tmp/pytest-of-marcedit/pytest-0/test_existing_upload_migrates_0/legacy.mrc: near "RETURNING": syntax error
  =========================== short test summary info ============================
  FAILED tests/test_job_files.py::test_attach_file_works_without_sqlite_returning
  FAILED tests/test_job_file_migration.py::test_existing_upload_migrates_once_to_immutable_version
  2 failed, 12 passed in 0.67s
  ```

- Focused GREEN command:
  `docker run --rm --network none -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/prod-fixes-task-167-170:/workspace:ro -w /workspace -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest tests/test_job_files.py::test_attach_file_works_without_sqlite_returning tests/test_job_file_migration.py -q`

  Output (exit 0; 14 passed, 0 skipped):

  ```text
  ..............                                                           [100%]
  14 passed in 0.66s
  ```

- Complete applicable GREEN command:
  `docker run --rm --network none -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/prod-fixes-task-167-170:/workspace:ro -w /workspace -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest tests/test_job_files.py tests/test_job_file_migration.py tests/test_job_file_workflow.py tests/test_job_file_mutations.py -q`

  Output (exit 0; 85 passed, 0 skipped):

  ```text
  ........................................................................ [ 84%]
  .............                                                            [100%]
  85 passed in 3.27s
  ```

- Runtime SQL check: `rg -n "RETURNING id" marcedit_web/lib/job_files.py`
  produced no output and exited 1 as expected.
- Static checks: `python3 -m py_compile marcedit_web/lib/job_files.py` and
  `git diff --check` produced no output and exited 0.
- Implementation commit: `4947716 fix: support production SQLite job files`.
- Independent review: spec compliant and task quality Approved, with no
  Critical, Important, or Minor findings.
