# TASK-092 — Track local tickets for rollback checkpoints

**Status:** Completed
**Priority:** Tier 3 — workflow safety
**Source:** User request: commit ticket context regularly so changes can be
rolled back if necessary

## Title

Version-control local ticket markdown files.

## Scope

- Change `.gitignore` so `.tickets/*.md` files can be committed.
- Preserve ignores for other local-only agent workflow artifacts.
- Commit the ticket-tracking change as a rollback checkpoint.

## Success Criteria

1. `.tickets/*.md` files appear in `git status` instead of being ignored.
2. TASK-090 and TASK-091 can be committed with the workflow change.
3. The checkpoint is committed on local `main`.
