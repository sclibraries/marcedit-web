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

Status: In-Progress
