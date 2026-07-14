Title: Diagnose job-detail file attachment and Routledge workflow

Scope:
- Trace why a cataloger cannot attach a MARC file from the Jobs detail page.
- Validate the proposed multi-file Routledge workflow against current job,
  batch operation, task, history, and export behavior.
- Design file-centered work items so one job can contain independently
  versioned, reviewed, checked-out, and exported MARC files.

Success Criteria:
- The attachment failure is classified as a defect, missing capability, or
  intended navigation behavior with code and test evidence.
- Every step of the proposed workflow is marked supported, indirect, or
  unsupported.
- An approved design specifies file ownership, versions, checkout, approval,
  exports, migration, failure handling, and end-to-end acceptance.

Design: [Job File Work Items](../docs/superpowers/specs/2026-07-14-job-file-work-items-design.md)

Design Evidence:
- Root cause confirmed: Jobs detail renders the shared files table but no file
  uploader; attachment exists only on Home's Job Workspace path.
- Current workflow verification: 106 focused tests passed in the supported
  Python 3.9 container.
- Approved design covers multiple file work items per job, exclusive file
  checkout, immutable versions, per-file status/review, labeled exports,
  conservative migration, atomic failure handling, and Routledge acceptance.
- Spec self-review resolved checkout requirements for exports, explicit file
  status transitions, aggregate activity, and immutable migration storage.

Status: Completed
