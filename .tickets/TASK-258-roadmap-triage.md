Title: Triage open tickets into milestones and create ROADMAP.md

Status: In-Progress
Milestone: M1
Size: M

Why:
- Open tickets have no ordering or grouping; neither the human nor Codex can see what is next.

Scope:
- Read every non-Completed ticket and classify: keep / merge / close as obsolete.
- Add `Milestone:` (and `Size:` where known) to open tickets.
- Create tracked `ROADMAP.md` with ordered milestones and their tickets.
- Write the Ready ticket for a backlog-index script (Codex implements).

Out of scope:
- Any code (orchestrator does not write code).
- Promoting feature tickets to Ready (separate per-ticket planning).

Success Criteria:
- Every open ticket appears in exactly one milestone in ROADMAP.md or is marked obsolete with a reason.
- User approves milestone order.
