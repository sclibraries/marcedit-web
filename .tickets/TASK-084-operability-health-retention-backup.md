# TASK-084 — Operability: health probe, retention/VACUUM, backup/restore

**Status:** In-Progress
**Priority:** Tier 3 — Service foundation
**Source:** Deep code audit 2026-06-17 — horizon critic (operability gaps)

## Title

Add the operational surfaces a small team needs to run this as a service on
Oracle Linux: real readiness signalling, bounded audit/DB growth, and a tested
backup/restore.

## Scope

- Add a readiness probe distinct from "streamlit started" (DB reachable +
  writable); wire into the systemd unit and the Docker `HEALTHCHECK`.
- Audit-table / JSONL retention + prune + periodic `VACUUM` — the audit table
  grows per page render today, unbounded.
- A documented, scriptable backup/restore for `data/marcedit.db` (+ WAL/SHM)
  and the audit JSONL. Stdlib `sqlite3` only (conservative-version friendly).

## Success Criteria

1. The health endpoint reflects DB reachability/writability, not just process
   liveness.
2. A retention job prunes/vacuums on a schedule without locking out the app
   (WAL-safe).
3. The backup/restore procedure is tested — a restore yields a working DB.
4. Deploy docs updated.

## Implementation Plan

Ticket link: `.tickets/TASK-084-operability-health-retention-backup.md`

1. Readiness checkpoint:
   - Add a stdlib `python -m marcedit_web.ops.health` command that initializes
     schema and verifies the SQLite DB accepts a rollbacked write transaction.
   - Wire Docker `HEALTHCHECK` to require both Streamlit liveness and DB
     readiness.
   - Wire private systemd units with `ExecStartPre` readiness checks; leave the
     public unit DB-free.
   - Add tests and commit.
2. Retention/VACUUM checkpoint:
   - Add audit SQL + JSONL pruning helpers and a CLI command.
   - Document a systemd timer/cron invocation.
   - Add tests and commit.
3. Backup/restore checkpoint:
   - Add stdlib backup/restore helpers/CLI around SQLite online backup and
     audit JSONL copy.
   - Add restore verification tests and docs.
   - Commit TASK-084 completion.

## Progress

- Readiness checkpoint implemented:
  `python -m marcedit_web.ops.health` initializes schema and verifies the
  private SQLite DB accepts a rollbacked write transaction. Docker healthcheck
  now requires both DB readiness and Streamlit liveness. Private systemd units
  run readiness with `ExecStartPre`; the public unit remains DB-free.
- Retention/VACUUM checkpoint implemented:
  `python -m marcedit_web.ops.maintenance retention --retain-days N` prunes
  SQL audit rows and dated JSONL audit files, checkpoints WAL, and runs
  `VACUUM`. Deployment docs include the schedulable command.
