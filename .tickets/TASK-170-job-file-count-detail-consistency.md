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

Status: In-Progress
