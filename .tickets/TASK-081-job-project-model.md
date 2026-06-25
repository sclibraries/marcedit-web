# TASK-081 — Job/project model (multi-file, collaboration-aware schema)

**Status:** Todo
**Priority:** Tier 3 — Service foundation
**Collaboration:** Foundation built now; sharing UI deferred to TASK-086
**Source:** Deep code audit 2026-06-17 — horizon (job model / multi-file)
**Depends on:** TASK-083 (concurrency); informs TASK-082, TASK-086

## Title

Replace the single-active-upload-per-user model with a server-side job/project
entity whose schema supports an owner and a forward-compatible sharing
dimension.

## Scope

- Today `upload_persistence.py:23-25` enforces exactly one active upload per
  user, session-scoped; a new upload flips the prior to inactive. This fits a
  demo, not a unit ingesting multiple vendor files daily.
- Introduce a named `project`/`job` entity (server-side) that can hold one or
  more uploaded `.mrc` files; uploads attach to a job, not a global per-user
  slot.
- Schema carries `owner_id` plus a sharing dimension (e.g. a `job_access` table
  or shared flag) designed in NOW, even though the sharing UI ships in the
  collaboration epic. Chosen model: shared project + record check-out/locking.
- Migrate existing per-user uploads into a default personal job (no data loss).

## Success Criteria

1. A user can create/select a named job containing >=1 file; uploads attach to
   the job.
2. The schema carries `owner_id` plus a forward-compatible sharing field with
   no sharing UI required yet; documented for TASK-086.
3. Existing uploads migrate cleanly with no data loss.
4. Focused tests and the Docker test suite pass before completion.
