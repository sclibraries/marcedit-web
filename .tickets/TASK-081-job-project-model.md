# TASK-081 — Job/project model (multi-file, collaboration-aware schema)

**Status:** Completed
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

## Implementation Plan

Ticket link: `.tickets/TASK-081-job-project-model.md`

1. Schema checkpoint:
   - Add schema v6 tables `jobs` and `job_access`.
   - Add nullable `uploads.job_id` with a migration that assigns existing
     uploads to a default personal job per user.
   - Add tests for new schema and migration behavior.
2. Library checkpoint:
   - Add server-side job helpers for creating/listing jobs and selecting the
     default job.
   - Make upload persistence attach each upload to a job while preserving the
     current active-upload restore behavior.
   - Add tests and commit.
3. UI/documentation checkpoint:
   - Add a minimal job selector/creator where uploads happen, without adding
     sharing UI.
   - Document the `job_access` model for TASK-086.
   - Run Docker suite and complete the ticket.

## Progress

- Schema checkpoint implemented:
  v6 adds `jobs`, `job_access`, and `uploads.job_id`. Existing upload rows are
  migrated into a per-user `Personal uploads` job without losing upload rows.
- Library checkpoint implemented:
  `marcedit_web.lib.jobs` can create/list jobs, ensure the default personal
  job, and list a job's uploads. `record_upload` attaches persisted uploads to
  a job while preserving the existing active-upload restore behavior.
- UI/documentation checkpoint implemented:
  Home lets signed-in catalogers select or create their own jobs before upload.
  Sharing is documented for TASK-086 but not exposed in the UI yet.
