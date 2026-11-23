Title: Record the rewrite ADRs and roadmap

Status: Completed
Size: S
Tier: small — documentation only
Milestone: M1 — Workflow
Base: the local `main` commit that adds this ticket
Branch: none (orchestrator documentation)

Why:
- The owner approved the React + Flask rewrite on 2026-11-23, which replaces
  the roadmap's "stay on Streamlit" direction (TASK-252).

Scope:
- ADRs 0001 to 0004 in `docs/adr/`; `ROADMAP.md` milestones.

Out of scope:
- Code, tests, and `ARCHITECTURE.md` (it describes `main` and changes with
  the tickets that build each part).

Acceptance tests:
- `python3 scripts/backlog.py --check ROADMAP.md` passes.

Handoff:
- (none; written by the orchestrator)

Review:
- Owner OK 2026-11-23 (6243782). `scripts/backlog.py --check ROADMAP.md` passes.
