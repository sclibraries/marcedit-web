# TASK-019 — Quotas, operation timeouts, security-event audit log

**Status:** Completed
**Stage:** 19 (per `the-goal-of-this-sequential-sifakis.md` v3)

## Title

Add per-feature byte caps for every upload / import path, a session-
aggregate cap, hard timeouts on archive expansion, and an append-only
JSONL audit log for security-relevant events. The Stage 17 sandbox
already enforces CPU/memory/wall-clock limits on user-task execution;
this stage extends quotas + audit to the *non-sandbox* I/O surface.

## Scope

- New `marcedit_web/lib/quotas.py`:
  * Constants for `MAX_UPLOAD_BYTES` (batch upload), `MAX_DIFF_BYTES`,
    `MAX_TASKSFILE_BYTES`, `MAX_SESSION_BYTES`. Each env-overridable
    via `MARCEDIT_WEB_MAX_*_BYTES`.
  * `QuotaExceeded(kind, attempted, limit)` exception.
  * `check_upload(size, kind)` + `check_session_aggregate(running, increment)`.
- New `marcedit_web/lib/audit.py`:
  * `audit_event(kind, user=..., **fields)` appends one JSONL line to
    `data/audit/audit-YYYY-MM-DD.log`. Never raises — IO failures
    fall back to a `logger.warning`.
  * Audit-log path env-overridable via `MARCEDIT_WEB_AUDIT_DIR`.
- Wiring:
  * `Home.py` upload → check_upload (kind=upload) + audit `upload-accepted`
    / `upload-rejected`. On accept, accumulate into session-aggregate.
  * `pages/6_Diff.py` uploads (old + new sides) → check_upload (kind=diff)
    + audit on accept/reject.
  * `render/tasks.py` `_do_marcedit_import` → check_upload (kind=tasksfile)
    + audit `tasksfile-imported` / `tasksfile-rejected` (also for `.task`
    archive entry, with `archive-imported`).
  * `render/tasks.py` save callback → audit `task-saved` (with
    `mode=form|code` and `is_admin` flag).
  * `render/tasks.py` delete callback → audit `task-deleted`.
  * `render/tasks.py` sandbox run → audit `sandbox-timeout` or
    `sandbox-nonzero-exit` if `SandboxResult` reports either.

  Originally this ticket also called for a `download-issued` event on
  every export surface. Walked back during implementation and aligned
  in TASK-029: downloads of bytes the cataloger already had access to
  upload aren't security-relevant in this app's threat model, so they
  aren't audited. If your deployment needs egress logging, do it at
  the reverse-proxy layer. The live event list is enumerated in
  ``lib/audit.py`` and ``docs/deployment.md``.
- Archive expansion timeout: `marcedit_import.convert_task_archive`
  gets a hard total-decompressed-bytes cap (default 50 MB) and an
  entry-count cap (default 256) — protects against zip bombs +
  thousands-of-entry archives.
- Tests in `tests/test_quotas.py` + `tests/test_audit.py`:
  * Quota constants honor env overrides.
  * `QuotaExceeded` raised at the right threshold.
  * `audit_event` writes a parseable JSONL line; concurrent writes
    don't interleave (threaded smoke).
  * `convert_task_archive` rejects an archive that blows the cap.

## Out of scope

- Anonymous-user refusal handling (Stage 21).
- Per-user persistent quotas across sessions (operational, not security).
- Audit-log retention rotation — write-only here; ops handles rotation
  via logrotate.
- Sandbox-level timeouts — already in Stage 17.

## Success Criteria

1. Each upload site rejects an over-cap payload with a clear error and
   emits an `upload-rejected` audit event.
2. Each accept path emits the matching `upload-accepted` event.
3. `convert_task_archive` of a 60-MB-decompressed test fixture is
   rejected with `archive-rejected` audit and a user-visible error.
4. `data/audit/audit-YYYY-MM-DD.log` is created on first event, has
   one JSON object per line, and survives concurrent writes from
   threads (no partial lines).
5. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_quotas.py tests/test_audit.py
docker compose run --rm marcedit-web pytest -q
```
