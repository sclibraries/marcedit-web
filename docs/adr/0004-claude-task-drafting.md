# ADR 0004: Claude drafts tasks inside fixed workflows

Date: 2026-11-23 · Status: accepted (owner) · Replaces Gemini and the note parser; restates invariant 3.

**Context.** Catalogers struggle to build tasks. No record content may go to an outside AI service.

**Decision.** The cataloger picks a workflow and writes at most 300 characters. The server rejects text
that looks like a record, sends Claude only those words and the workflow's allowed steps, and checks the
answer's schema, commands and tags. Failures are refused, not repaired. The draft opens in the task
builder and nothing runs until accepted. Off unless configured; the app works fully without it.

**Costs.** A short record snippet could still be typed. Requests outside the workflows are refused.
Depends on an outside service and an API key held on the server.
