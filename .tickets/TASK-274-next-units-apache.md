Title: Units, Apache and watchdog for the second service

Status: Todo
Size: M
Tier: major — deploy
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-274
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- ITS needs exact files to install, and the service must not be able to reach
  production.

Scope:
- `deploy/next/`: web unit, watchdog service and timer, sudoers (start, stop and
  restart of `marcedit-next` only), Apache snippet, attestation and environment
  examples.
- `docs/next-service.md`: what ITS installs once as root (user, folders, modes,
  SELinux check, unit, Apache), then deploy, rollback and removal by the owner.

Out of scope:
- The worker unit (R3), switchover, existing deploy files.

Likely files:
- `deploy/next/*`, `docs/next-service.md`, `tests/test_next_deploy.py`

Acceptance tests:
- The unit can write only its own `data/`, can't reach production's folder and
  listens on loopback only.
- On a real Apache (`httpd:2.4` container, basic sign-in standing in for
  Shibboleth) the snippet passes configtest; forged, duplicated and underscore
  identity headers never reach the app in place of the real ones; a request
  without sign-in never reaches it.
- The watchdog, with stand-in `systemctl` and `curl`: a service stopped after
  its first failed check stays stopped; three failures restart a running one.
- The sudoers file allows nothing but the three commands on that one unit.
- The document's root steps run in order on a clean machine without a step
  assuming a later one (the orchestrator reads it as ITS would).

Verification:
- Host: `python3 -m pytest -ra tests/test_next_deploy.py`
- Host: `python3 -m pytest tests/test_deploy_units.py tests/test_docker_compose_config.py`
- The Apache check as a script the orchestrator can rerun, output pasted.

Plan:
1. Unit, sudoers, environment example.
2. Apache snippet and its container check.
3. Watchdog.
4. Document.

Handoff:
-

Review:
-
