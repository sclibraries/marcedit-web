Title: API client and session expiry

Status: Todo
Size: M
Tier: major — auth
Milestone: M2 — R1
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-271
Contract: docs/superpowers/specs/2026-11-24-r1-sign-in-second-service.md (local-only)

Why:
- Catalogers keep pages open for hours. An expired Shibboleth session must
  never lose typed work, send a change twice, or save one person's work under
  another's name.

Scope:
- One API client used by every screen, with the contract's "Session expiry"
  table. It never retries a change.
- Screens: checking access, awaiting approval, revoked, session ended (covering
  the page), couldn't confirm, and the `signed-in` page.
- `frontend/dev/expiry-proxy.mjs`: a small Node script (no dependencies) that
  forwards to the API with a stand-in identity and, on request, redirects API
  calls to another origin, answers 502, cuts an answer short or delays one.
  With its start command in `frontend/README.md`.

Out of scope:
- Storing typed work in the browser; sign-out; Admin page.

Likely files:
- `frontend/src/api/*`, `frontend/src/access/*`, their tests,
  `frontend/dev/expiry-proxy.mjs`, `frontend/README.md`

Acceptance tests:
- Each row of the contract's table gives its message (one parametrized test:
  opaque redirect; 200 HTML without the marker; 401 signed-out; 403 with the
  marker; 500 with the marker; 502 without; cut-off JSON; network failure).
- After an expiry, text typed in a form is still there when the same person
  signs back in, and exactly one change was sent in all.
- A change that answers "saved" after another call reported the expiry is shown
  as saved.
- After an unknown result the current state is loaded before the change can be
  sent again, and the message never says "not saved": the first may still
  finish.
- If someone else signs in, or access was revoked, the old page is unmounted;
  a late answer for the old person neither shows data nor clears the message.
- While covered, the page can't be read or operated, by keyboard or screen
  reader either.
- Two expired calls at once show one message.
- The orchestrator repeats expiry in a real browser through the proxy script,
  because jsdom can't make an opaque redirect.

Verification:
- `git archive HEAD frontend marcedit_web/schemas/api | docker run --rm -i node:24-slim sh -c 'set -e; mkdir /w; tar -x -C /w; cd /w/frontend; npm ci; npm run typecheck; npm run types:check; npm test; npm run build'`

Plan:
1. Client and result table.
2. Identity state and covered page.
3. Screens.
4. Proxy script.

Handoff:
-

Review:
-
