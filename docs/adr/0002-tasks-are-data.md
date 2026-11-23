# ADR 0002: Tasks are data; runs use killable subprocesses

Date: 2026-11-23 · Status: accepted (owner) · Changes invariants 1, 2 and 9 when built.

**Context.** Saved tasks are generated Python run in a sandbox subprocess. open-marc-tasks runs the same
work from JSON that is never executed as code. Its regexes can still backtrack without limit.

**Decision.** Saved tasks become open-marc-tasks documents. Raw-Python authoring and execution are
removed. Runs (in the durable worker) and previews execute outside the web process in killable
subprocesses with resource and time limits. A run stores every task it uses, so later edits don't change
it. The `operations` table is rebuilt to allow the new kinds of run; the migration refuses if it has rows.

**Costs.** Hand-written Python tasks can't run and must be rebuilt as steps. A second service (the
worker) must be installed on the host.
