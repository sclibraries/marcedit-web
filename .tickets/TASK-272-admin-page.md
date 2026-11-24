Title: Admin page

Status: Todo
Size: S
Tier: normal — new screen on reviewed routes
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-272
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- Parity row 2: admins approve or deny people, set roles and manage domains.

Scope:
- `/admin`: waiting people first, then people, then domains, over TASK-269's
  routes and TASK-271's client. Shown in the sidebar to admins only.
- Entries from the settings say so and have no remove, revoke or demote button.
- Removing your own admin role or access asks first.

Out of scope:
- Search, paging, bulk changes.

Likely files:
- `frontend/src/admin/*`, shell navigation

Acceptance tests:
- Approve, deny (revoke), change role, add and remove a domain each update the
  list from the server's answer, so the page never shows a change that wasn't
  saved.
- One change at a time: while one is being sent the other buttons are disabled,
  so an older list can't replace a newer one.
- A refused change shows its message beside that row and leaves the rest
  usable.
- Removing your own admin role asks first, then leaves the page.
- The orchestrator uses it by keyboard in a browser.

Verification:
- `git archive HEAD frontend marcedit_web/schemas/api | docker run --rm -i node:24-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w/frontend; npm ci; npm run typecheck; npm run types:check; npm test; npm run build'`

Plan:
- (S)

Handoff:
-

Review:
-
