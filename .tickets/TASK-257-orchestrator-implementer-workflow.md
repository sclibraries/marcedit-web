Title: Establish orchestrator / implementer agent workflow

Status: Completed

Scope:
- Split agent instructions: shared rules + implementer role in `AGENTS.md` (Codex CLI); orchestrator role in `CLAUDE.md` importing `AGENTS.md`.
- Claude Code is orchestrator only: architecture, roadmap, tickets, plans, review. No production code or tests are written by Claude.
- Codex CLI is the sole implementer, including running the Docker test suite.
- Create tracked `ARCHITECTURE.md` (seeded from local `docs/application-overview.md`).
- Define ticket lifecycle (Todo → Ready → In-Progress → In-Review → Completed / Blocked) and the Ready-ticket handoff template.
- Delete stray `AGENTS copy.md` and `README copy.md` (from an unrelated project).

Out of scope:
- Roadmap/milestone triage of existing Todo tickets (follow-up ticket).
- Backlog index script (follow-up ticket, implemented by Codex).
- Any application code change.

Success Criteria:
- `AGENTS.md` contains shared rules, the implementer role, and the handoff contract; no Claude-specific wording.
- `CLAUDE.md` imports `AGENTS.md` and adds only orchestrator-specific rules; no duplicated rule text.
- `ARCHITECTURE.md` exists at repo root, describes module boundaries, invariants, storage, deploy constraints, and is reviewed by the user.
- Stray copy files removed.
- User approves the structure.

Progress (2026-10-09):
- Done: AGENTS.md rewritten (shared rules, roles, lifecycle, Ready template, Codex workflow, verification commands). CLAUDE.md = `@AGENTS.md` + orchestrator role.
- Done: ARCHITECTURE.md drafted from origin/main (ab82922), verified by a read-only code survey; not yet committed.
- Done: deleted `AGENTS copy.md`, `README copy.md`.
- Finding: local `main` is stale (0 ahead, 224 behind origin/main). ARCHITECTURE.md and this ticket must be committed on a branch from origin/main, not on local main.
- User approved ARCHITECTURE.md and structure (2026-10-09). Local main fast-forwarded to origin/main ab82922 (no collisions: TASK-254 local copy is origin + one appended note, restored; local TASK-193 file is a review note for the same TASK-193 work).
