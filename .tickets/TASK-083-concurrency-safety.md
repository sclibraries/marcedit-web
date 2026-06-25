# TASK-083 — Concurrency safety for shared SQLite and active-job swaps

**Status:** Completed
**Priority:** Tier 3 — Service foundation
**Collaboration:** Prerequisite for record check-out/locking (TASK-086)
**Source:** Deep code audit 2026-06-17 — horizon critic (data-race safety)

## Title

Make shared-SQLite access and the active-job/upload swap safe under multiple
concurrent catalogers, and add the locking primitive collaboration will build
on.

## Scope

- The app runs as one Streamlit process serving multiple catalogers; the
  per-page audit write plus the "flip prior active upload then write new"
  sequence can race. Audit and fix: ensure WAL + correct transactions, and
  serialize the active-job flip.
- Add an advisory lock primitive (a lock table keyed by job/record, with holder
  + expiry) that supports atomic acquire / release / expire — the substrate for
  record check-out.

## Success Criteria

1. Two simulated concurrent users uploading/editing don't corrupt rows or lose
   writes (test with concurrent connections).
2. A job/record lock can be acquired, released, and expired atomically.
3. No regression in single-user flows; focused tests and the Docker test suite
   pass before completion.
