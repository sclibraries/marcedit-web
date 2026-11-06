Title: Generate the ROADMAP.md backlog from ticket files

Status: In-Review
Milestone: M1
Size: S
Base: the local `main` commit that adds this ticket
Branch: task-259-backlog-index

Why:
- Ticket files are the single source of truth for scope and status, but
  nothing shows the backlog in one place. A hand-maintained list in
  ROADMAP.md would drift from the tickets within days. A deterministic
  script (Rule 5) keeps them in agreement and lets the orchestrator and CI
  detect tickets with no milestone or an unrecognized status.

Scope:
- Add `scripts/backlog.py` (stdlib only, Python 3.9).
- Parse every `.tickets/*.md`. Ticket key = filename stem (IDs are not
  unique: e.g. two TASK-046 files exist). Extract:
  - Status, from the first of: a line `Status: X`, a line `**Status:** X`,
    or a `## Status` heading (value = next non-empty line). Normalize to the first word (`In-Progress (notes…)` → `In-Progress`).
  - Title, from `Title: X`, else the first `# ` heading.
  - Milestone, from `Milestone: X` or `**Milestone:** X` (a code like `M1`).
  - Size, from `Size: X` or `**Size:** X` (S/M/L, optional).
- ROADMAP.md contains a hand-written ordered milestone list. Each item
  starts `N. **<code> — <name>**`. The script reads the codes in that order.
- `python scripts/backlog.py --write ROADMAP.md` replaces only the text
  between `<!-- backlog:start -->` and `<!-- backlog:end -->` with one
  markdown table per milestone, in roadmap order. Columns: Ticket
  (relative link to the file), Title, Status, Size. Rows sorted by
  filename. Only tickets whose status is not `Completed` or `Obsolete`.
  Open tickets with no milestone go in a final "Unassigned" table.
- `python scripts/backlog.py --check ROADMAP.md` exits non-zero and lists
  each problem when:
  - an open ticket has no milestone, or names a milestone missing from
    the roadmap list;
  - a ticket's status is not one of Todo, Ready, In-Progress, In-Review,
    Completed, Blocked, Obsolete (missing status counts);
  - the generated block in ROADMAP.md differs from what `--write` would
    produce.
  Otherwise it exits 0.

Out of scope:
- Rewriting or reformatting existing ticket files.
- Creating ROADMAP.md content (orchestrator owns it; use fixtures in tests).
- Adding `--check` to CI (follow-up once the backlog is clean).

Likely files:
- `scripts/backlog.py` (new)
- `tests/test_backlog_script.py` (new)

Acceptance tests (tmp_path fixtures, no dependency on real tickets):
- All three status syntaxes and the `In-Progress (notes…)` form parse to
  the same status. Why: existing tickets use all three (about 150 use
  `**Status:**`, 7 use `## Status`), and the backlog must not silently
  drop any of them.
- Two files sharing an ID both appear. Why: duplicate IDs exist today, and
  keying by ID would hide one.
- Completed and Obsolete tickets are excluded; Blocked tickets are
  included. Why: the roadmap shows remaining work, and blocked work is
  remaining work.
- Tables follow the roadmap's milestone order, not alphabetical order.
  Why: the order is the priority.
- `--write` leaves every byte outside the markers unchanged. Why: the
  milestone narrative is hand-written by the orchestrator.
- `--check` fails for: no milestone, unknown milestone, unknown or missing
  status, stale generated block. It passes right after `--write`. Why: it
  is the drift alarm; a check that cannot fail is useless (Rule 9).
- `--write` on a file without markers exits non-zero and does not modify
  the file. Why: never clobber hand-written content.

Verification:
- From the worktree, the Docker suite command in AGENTS.md (scripts/ is
  mounted).
- `python3 scripts/backlog.py --check ROADMAP.md` against the real repo:
  report its output in the handoff. It may legitimately fail while
  triage (TASK-258) is in progress; do not edit tickets to make it pass.

Plan:
- (S — none)

Handoff:
- (implementer fills in)

Review:
- (orchestrator fills in)
