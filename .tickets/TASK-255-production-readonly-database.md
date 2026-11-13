Title: Diagnose production SQLite readonly error after TASK-254 deployment

Status: Obsolete
Milestone: M0

Scope:
- Diagnose the production database write failure without changing data or guessing permissions.
- Guide a targeted repair based on server filesystem and service evidence.

Success Criteria:
- Identify the database, directory, journal permissions, mount, or service restriction causing the failure.
- Production readiness probe succeeds as marcedit and the app starts without the SQLite error.
- Record the actual repair and verification results.

Evidence:
- User deployment log confirms fast-forward d1ab66e to 5a626d3 and successful backup at /home/marcedit/backups/marcedit-web/2026-10-06-task-254.
- Shell health probe as marcedit against /var/www/html/marcedit-web/data/marcedit.db failed with attempt to write a readonly database before scripted restart.
- User then manually restarted the service; app traceback fails in db._seed_access_control.
- No database or deployment code changed in this release.
- Need server ownership/modes for database, WAL/SHM, parent directory, resolved path, mount options and effective service user/write paths. No live server inspection or permission changes performed yet.

Closed — 2026-11-13:
- Owner reports the readonly-database error no longer occurs in production.
  No health-probe output or server permission facts were captured, and the
  original cause was never identified.
- If it recurs, reopen and first run, as the service user:
  `sudo -u marcedit /var/www/html/marcedit-web/.venv/bin/python -m marcedit_web.ops.health`
  then collect ownership and modes of `data/`, `marcedit.db`, `-wal` and `-shm`.
