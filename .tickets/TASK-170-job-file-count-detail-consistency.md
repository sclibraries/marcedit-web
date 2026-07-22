Title: Make shared-job file counts agree with visible detail rows

Scope:
- Reproduce a job card reporting attached files while the opened job renders no
  file rows.
- Make the summary count and detail list use the same accessible,
  non-archived `job_files` visibility definition.
- Do not count legacy uploads that have not materialized or expose archived or
  inaccessible data.

Success Criteria:
- The job-card file count equals the number of rows returned by the default
  opened-job file list.
- Archived job files and unmaterialized legacy uploads do not inflate the
  visible count.
- Owner/editor/viewer authorization and archive semantics remain intact.
- Intent-focused and applicable suites pass with every skip reported, and
  review has no unresolved Critical or Important findings.

Status: Completed

Evidence:
- RED: `python3 -m pytest tests/test_jobs.py -q` exited 1 with 3 failed,
  26 passed, 0 skipped, and 198 warnings. The durable-file fixture counted 0
  instead of 1, the unmaterialized legacy upload counted 1 instead of 0, and
  the archived-file regression counted 0 while detail rendered 1 visible row.
- Authoritative GREEN (Python 3.9):
  `docker run --rm --network none -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/prod-fixes-task-167-170:/workspace:ro -w /workspace -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest tests/test_jobs.py tests/test_job_files.py tests/test_collaboration.py -q`
  exited 0 with 74 passed, 0 skipped, and 0 warnings in 2.51s.
- Static: `python3 -m py_compile marcedit_web/lib/jobs.py` and
  `git diff --check` both exited 0 with no output.
- Implementation: `469119f` (`fix: align job file counts with detail`).
- Review: spec compliant and task quality Approved, with no Critical,
  Important, or Minor findings.
