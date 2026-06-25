# TASK-087 — Untrack the internal workflow files committed before the gitignore rule

**Status:** Completed — history rewritten 2026-06-18; internal files purged from all 66 unpushed commits
**Priority:** Tier 0 — Pre-push hygiene (do before the next `git push`)
**Source:** Discovered 2026-06-18 while working TASK-073

## Resolution (2026-06-18)

Chose history rewrite over a tip-only `git rm --cached` (the latter would have
left the 20 files in 23 historical commits, leaking on push). Used built-in
`git filter-branch --index-filter` (git-filter-repo not installed) over
`origin/main..HEAD`, stripping `.tickets/`, `docs/superpowers/`, `CLAUDE.md`,
`AGENTS.md`, `docs/application-overview.md`.

Verified: 0 tracked internal files at tip; **0 commits across all 66** touch
those paths (exhaustive per-commit blob scan); non-internal tracked content
byte-identical to the pre-rewrite tip (empty diff); 66 commits preserved;
focused suite 56 passed; all on-disk artifacts intact (restored from a
`/tmp` backup as a precaution).

**Recovery refs (point at the OLD dirty history — do NOT push them):**
`refs/tags/backup/pre-task-087-rewrite` and `refs/original/refs/heads/main`.
A plain `git push origin main` is safe (pushes only the clean main). Avoid
`git push --tags` / `--mirror` until these are dropped. Drop when satisfied:
`git tag -d backup/pre-task-087-rewrite && git update-ref -d refs/original/refs/heads/main && git reflog expire --expire=now --all && git gc --prune=now`.

## Title

Stop tracking the local-only agent/workflow artifacts that were committed to
local history before `.gitignore` was updated to exclude them, so they don't
reach the public repository on the next push.

## Background

`.gitignore` declares `/.tickets/`, `/docs/superpowers/`, `/CLAUDE.md`,
`/AGENTS.md`, and `/docs/application-overview.md` as local-only workflow
artifacts that "must never be committed to the public repository." Newer
tickets (TASK-069+) are correctly untracked. But 20 files were committed to
**local history** before that rule existed — added in `6333cec` ("Plan delete
subfield by matched value") and `c146222` ("Complete TASK-068"):

- `.tickets/TASK-059…TASK-068` (10 ticket files)
- `docs/superpowers/plans/*` and `docs/superpowers/specs/*` (10 plan/spec files,
  dated 2026-06-09 … 2026-06-11)

They are **not** on `origin/main` (verified: 0 there), but the branch is ahead
of origin by many commits. Pushing as-is would publish all 20.

## Scope

- `git rm --cached` the 20 tracked paths (they are already ignored, so this only
  stops tracking; working-tree copies stay on disk).
- Verify `git ls-files .tickets/ docs/superpowers/ CLAUDE.md` and the other
  ignored paths return nothing afterward.
- Decide whether a single new commit removing them from the tip is sufficient
  (acceptable: they were never pushed, so the files appearing then disappearing
  in unpushed local history is harmless) or whether the introducing commits
  should be rewritten. Default: a single removal commit — simplest, and origin
  never saw them.

## Success Criteria

1. `git ls-files` reports no files under `.tickets/`, `docs/superpowers/`,
   nor `CLAUDE.md` / `AGENTS.md` / `docs/application-overview.md`.
2. The working-tree copies of all those files still exist on disk (local
   workflow unaffected).
3. Confirmed before any `git push` to origin.
