# TASK-088 — Access & Trust Model (public light tier + authenticated tier)

**Status:** Completed — merged to local main (fast-forward, commits 684a8e9..8f2374d, 20 commits) on 2026-06-22. 10 tasks TDD-implemented, per-task reviewed, final whole-branch review (opus) passed; 65 feature tests green. Public-tier DB-free property hardened in code after final review.
**Priority:** Tier 3/4 — foundation for open-web exposure and the collaboration epic
**Source:** Brainstorm 2026-06-22 (Rob OConnell) — open-web availability + Five-College collaboration
**Spec:** `docs/superpowers/specs/2026-06-22-access-trust-model-design.md`
**Depends on / sequences:** TASK-074, TASK-076 (sandbox hardening — private unit), TASK-075
(systemd hardening — public-unit isolation), TASK-084 (operability). Extends TASK-047 (OAuth),
TASK-073 (attestation). Foundation for the collaboration epic (TASK-081/083/085/086).

## Title

Establish a two-tier access model: an anonymous public "light" tier (upload → View / Validate /
Report / Marc Tools convert, ephemeral, no sandbox, no persistence) and an authenticated tier
(Google OAuth + DB-backed allowlist/approval + Admin/Cataloger RBAC), deployed as two systemd
units from one artifact so the public surface cannot reach the sandbox or catalog DB by
construction.

## Scope

- **Run mode** (`MARCEDIT_WEB_MODE=public|private`, default `private`): `App.py` builds the
  `st.navigation` page set conditionally. Public mode registers only Home(upload), View, Validate,
  Report, Marc Tools; the Tasks/sandbox page is never registered.
- **Two systemd units** from one venv/artifact: public (anonymous, ephemeral, no catalog DB, own
  resource budget) and private (auth required, shared `data/marcedit.db`).
- **`lib/authz.py`** authorization layer over `identity.current_user()`: `approved(role)` /
  `pending` / `revoked` / `denied`, with domain auto-approval and pending-queue fallback. Single
  gate in `App.py` before `st.navigation(...).run()` on the private unit.
- **Roles:** `admin`, `cataloger`. Admin page: approve/revoke users, edit `allowed_domains`,
  adjust lock-expiry default, force-release locks (lock actions exercised by Spec B), retention/backup.
- **Tenancy:** single shared pool, private-by-default; "share" makes a project visible to all
  approved catalogers.
- **Schema v3→v4:** add `users` and `allowed_domains` tables (create-only migration). Reuse
  `audit_events` for `auth.*` events. Bootstrap admins via `MARCEDIT_WEB_ADMIN_EMAILS`.
- **Public-tier abuse controls:** upload byte cap (pre-parse) + existing MARC-length guard,
  per-op timeouts (TASK-019), proxy-level rate limiting, separate process budget (TASK-075).

## Out of scope (→ collaboration spec / Spec B)

Per-record check-out/in, lock table, presence, provenance, job/project schema (TASK-081/083/
085/086). This ticket lands only the identity/role/tenancy/deployment foundation B builds on.

## Success Criteria

1. Public unit registers exactly the four read-only/transform pages; Tasks/sandbox is absent —
   asserted by a mode-registration test.
2. Private unit: anonymous → sign-in screen; allowlisted-domain login → auto-approved cataloger;
   other login → pending queue → admin approves → access; revoked → denied. Each path audited.
3. Bootstrap admin (`MARCEDIT_WEB_ADMIN_EMAILS`) exists on first boot; idempotent, never demotes.
4. v3→v4 migration is clean and re-runnable; focused tests + Docker suite pass before completion.
5. Public uploads are ephemeral (no `uploads` rows; purged on session end) and byte-capped.

## Notes

- Internal/local ticket — `.tickets/` and `docs/superpowers/` are gitignored and must NOT be
  committed to the public repo.
- Scale target 15–20 (Five Colleges) → stay on SQLite. MariaDB is the documented re-architecture
  trigger if/when the deployment goes multi-process.
