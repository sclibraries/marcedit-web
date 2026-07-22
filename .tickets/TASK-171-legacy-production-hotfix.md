Title: Backport production correctness fixes to the legacy single-service deployment

Scope:
- Start from the exact production revision `134bc16`.
- Backport the four production correctness fixes from TASK-167, TASK-168,
  TASK-169, and TASK-170 without bringing in TASK-156 durable operations.
- Preserve the existing `marcedit-web.service`, existing sudo permissions,
  and legacy deployment topology.
- Do not modify `scripts/deploy.sh`, systemd units, sudoers, Apache
  configuration, queue code, or worker configuration.
- Publish the completed work only on branch
  `legacy-hotfix-production-fixes`.
- Provide manual, branch-specific production deployment and rollback commands;
  do not use the legacy `scripts/deploy.sh`, because it pulls `origin/main`.

Success Criteria:
- Shared-job attachment works on production SQLite without SQL `RETURNING`.
- Job cards count only non-archived durable files visible in job detail.
- Replace-field-subfield-and-indicators supports optional `re.search` matching,
  preserves exact legacy tasks, validates invalid regexes before persistence or
  mutation, and reports invalid form regexes inline.
- View preserves MARC source order and warns about at most 20 adjacent tag
  inversions without mutating records.
- No durable-operation, worker, systemd, sudoers, Apache, or deployment-script
  change is present in the hotfix branch.
- Intent-focused RED/GREEN evidence, the complete Python 3.9 suite, static
  checks, and independent review are clean before the branch is pushed.
- Production deployment preserves `data/snapshots/` and all other untracked or
  ignored production data.

Verification Evidence:
- TASK-167 compatibility RED: the legacy-SQLite proxy produced the production
  `near "RETURNING": syntax error` failure (`2 failed, 12 passed`). GREEN:
  shared-file, migration, workflow, mutation, and collaboration coverage passed
  (`104 passed`) after all four runtime identity reads moved to same-cursor
  `lastrowid`.
- TASK-168 consistency RED: durable-file undercount, legacy-upload overcount,
  and archived/detail mismatch were reproduced (`3 failed, 26 passed`). GREEN:
  job, shared-file, and collaboration coverage passed (`74 passed`).
- TASK-169 regex RED/GREEN: transform coverage first failed on the missing
  flags (`5 failed, 57 passed`); builder/save coverage then failed on the
  missing options and validation (`5 failed, 28 passed`). The focused saved-task
  stack passed after implementation (`136 passed`).
- TASK-170 order RED/GREEN: the missing pure helper failed four tests
  (`4 failed, 20 passed`), and the absent View warning failed two behavioral
  tests (`2 failed, 6 passed`). Viewer/View/edit coverage passed after the
  non-mutating diagnostic was added (`41 passed`).
- Final combined production regressions passed under the Python 3.9 image:
  `310 passed in 5.03s`, with no skips or warning summary.
- The complete Python 3.9 suite passed: `1287 passed in 18.27s`, with no skips
  or warning summary. `compileall`, `git diff --check 134bc16...HEAD`, and the
  clean-worktree check passed.
- The fixed-base path audit contains only this ticket/design/plan, the seven
  scoped application modules, and their regression tests. It contains no
  deployment, environment-template, systemd, sudoers, Apache, worker, queue, or
  durable-operation path. The branch has no merge commits and its merge base is
  exactly `134bc16`.
- Independent task reviews found no unresolved Critical or Important issue.
  Final review of `134bc16..854c409` returned **Ready**, with three non-blocking
  future test-hardening notes: exercise editor-as-uploader explicitly, use a
  multi-file/multi-note aggregation fixture, and rerun migration after legacy
  source deletion.

Implementation Commits:
- `a8c5268` — production SQLite/shared-file compatibility.
- `f2dc356` — job-card/detail count consistency.
- `b98ceca`, `b8cc713`, `22dc2ee` — regex matching, form validation, and
  documentation compatibility.
- `11d00c9`, `854c409` — pure MARC inversion detection and View warning.

Status: Completed
