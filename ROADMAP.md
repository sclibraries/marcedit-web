# Roadmap — Smith Metadata Studio

The orchestrator keeps the milestone order and notes. The ticket tables
between the backlog markers are generated from `.tickets/` by
`scripts/backlog.py` (TASK-259); do not edit them by hand. Ticket files
are the source of truth.

## Milestones (in priority order)

1. **M0 — Production integrity**
   Keep what is deployed correct and recoverable. Nothing else ships
   until main matches production (TASK-260) and production writes
   work (TASK-255). TASK-117 and TASK-130 need one ITS session, for host
   RAM and cgroup facts and the production `.env` upload cap.
2. **M1 — Workflow**
   The orchestrator/implementer loop and backlog tooling. TASK-259 is
   the first Codex handoff.
3. **M2 — Cataloger value and speed**
   Per TASK-252: stay on Streamlit and spend effort on measured workflow
   speed and feedback rather than new infrastructure. Proposed, not yet
   ticketed:
   - Measure the slow morning refresh (auth, connection, first render)
     before guessing a cause.
   - Stop Workspace from running hidden tabs (Report walks every record).
   - Show progress while a refreshed session restores its batch.
4. **M3 — Code health**
   Low-risk Codex work: dead code, docstrings, tests, the supply-chain
   lockfile. TASK-098 and TASK-145 are close-out reviews that may need
   only a regression test.
5. **M4 — Host hardening (needs ITS)**
   systemd hardening, sandbox confinement, memory limits, and large-batch
   acceptance evidence on libtools2.
6. **M5 — Parked: durable operations**
   Blocked on one decision: re-enable the durable queue and worker
   (`runmode.DURABLE_OPERATIONS_ENABLED`) or redesign these features to
   run synchronously. TASK-252 argues against the large-file epic
   (TASK-162 to TASK-166) unless 2 GiB Diff is a proven need. TASK-097
   (presence) needs a separate yes/no.

## Unmerged branches

| Branch | State | Plan |
|---|---|---|
| `task-253-mrk-upload` | Deployed to production, not in main | TASK-260 |
| `task-134-confinement-fix` | Full TASK-134 work, about 300 commits behind | Port when TASK-134 is planned |
| `task-198-decoupled-workspace` | Streamlit-replacement prototype | Kept isolated per TASK-252 |
| `task-173-infrastructure-release-envelope` | Release-staging work, stale since 2026-07 | Decide: revive or archive |

## Backlog

<!-- backlog:start -->
<!-- backlog:end -->
