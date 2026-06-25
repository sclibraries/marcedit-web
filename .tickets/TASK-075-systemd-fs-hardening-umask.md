# TASK-075 — Add systemd hardening directives and a restrictive umask

**Status:** Todo
**Priority:** Tier 1 — Hardening (defense-in-depth)
**Source:** Deep code audit 2026-06-17 — findings S5 (LOW) + S6 (LOW)

## Title

Apply the missing systemd sandboxing directives and tighten file modes on the
SQLite DB, audit logs, and materialized task files.

## Scope

- `deploy/marcedit-web.service:21-27` has `NoNewPrivileges`, `ProtectSystem=
  strict`, `ProtectHome`, `PrivateTmp`, `ReadWritePaths` but none of:
  `CapabilityBoundingSet=`, `MemoryMax`/`TasksMax`, `RestrictNamespaces=true`,
  `ProtectKernelTunables/Modules/ControlGroups=true`, `PrivateDevices=true`,
  `RestrictSUIDSGID=true`, `LockPersonality=true`, `RestrictAddressFamilies`,
  `UMask=0077`. Add them.
- DB/audit/task `.py` files are created with the default umask (world-readable
  on the shared RHEL host). Either set `UMask=0077` in the unit and/or chmod
  0600 the files + 0700 the data subdirs on creation in `lib/db.py`,
  `lib/audit.py`, `lib/task_db.py` (covers non-systemd contexts).

## Success Criteria

1. `systemd-analyze security marcedit-web` exposure score improves measurably
   (record before/after in the ticket).
2. DB, audit, and task `.py` files are created mode 0600 / dirs 0700.
3. The app runs normally under the tightened unit (deploy smoke test).
4. Deploy docs updated.
