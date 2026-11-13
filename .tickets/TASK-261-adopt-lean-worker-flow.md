Title: Adopt the codex-worker-kit (lean flow, 2026-11-06)

Status: Completed
Size: M
Tier: small — agent rules and run tooling only; no application behavior change
Milestone: M1

Why:
- The human pasted every Codex prompt and did every merge by hand. The
  kit lets the orchestrator start worker rounds, records every round, and
  its 2026-11-06 lean flow moves checking onto the plan so builds stay
  one round and tests stay few.

Scope:
- New private repo `~/Projects/work/marcedit-web-coordination` (this repo
  is public): runner (`scripts/codex-run.sh`, `codex-events.py`),
  `codex-run.conf`, `handoffs/`, `runs/`, `docs/prompts/`,
  `docs/decisions/2026-11-06-orchestrator-runs-codex.md`, `board.json`.
- `AGENTS.md` (local-only): roles; `codex/TASK-NNN` branches in runner-made
  worktrees; handoff file in the coordination repo; Tier field and guide;
  one-session ticket size; Rule 14 (fewest tests); no weakening tests;
  Docker/network/dependency limits; implementer never pushes or merges.
- `CLAUDE.md` (local-only): rewritten around the runner — tiers, plan
  check, build, check against acceptance tests, fix-round limits, merge
  after the human's OK on a SHA, board, decisions.

Out of scope:
- Moving tickets out of `.tickets/` (they stay here, tracked).
- Retro-tiering or rerunning existing tickets; in-flight tickets finish
  under the old steps.
- Deploys (still the human's).

Acceptance tests:
- `DRY_RUN=1 scripts/codex-run.sh new TEST-000 …` prints the expected
  worktree, branch and sandbox — proves the config resolves.
- TEST-000 smoke round commits on `codex/TEST-000`, writes its handoff,
  verifies the model, and leaves `main` unmoved — proves the sandbox can
  commit and write records without touching main.
- `dashboard.py` renders this project from `board.json`.
- The human reviews AGENTS.md / CLAUDE.md and approves.

Handoff:
- 2026-11-06, orchestrator (rules and records only). Dry run ok. TEST-000
  round 01-start: exit 0, gpt-6-luna/xhigh (ok), commit d45a8ae on
  `codex/TEST-000`, main still 27d0e96. Dashboard renders TASK-253..261.
  Coordination repo commit a9adb03 (local only, no remote).

Review:
- (human)
