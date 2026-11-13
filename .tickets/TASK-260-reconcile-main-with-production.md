Title: Merge deployed TASK-253 commits into main before the next deploy

Status: Completed
Size: S
Milestone: M0

Why:
- Production runs TASK-253 release 1634873 (MRK upload acceptance and
  restored binary downloads). Its three commits (1634873, d1ab66e,
  de040fc) exist only on `task-253-mrk-upload`. A deploy from main would
  roll production back and re-break Marc Tools .mrc downloads: main's
  `render/marc_tools.py:400` references an undefined `stamp` (NameError),
  which 1634873 removes.

Scope:
- Merge `task-253-mrk-upload` into local main (human action under AGENTS.md roles).
- Resolve the only conflict: `.tickets/TASK-254-task-result-download.md`
  (add/add; keep main's version plus any branch-only lines).
- The untracked local `.tickets/TASK-253-mrk-upload-conversion.md` must be
  moved aside first or the merge will refuse; compare it with the branch copy.

Out of scope:
- Any other branch (task-134-*, task-173-*, task-198-* are tracked separately).

Success Criteria:
- `git merge-base --is-ancestor de040fc main` succeeds.
- Docker suite passes on merged main, including tests/test_marc_tools_download.py.

Resolution — 2026-11-13:
- Owner OK given. Merged `task-253-mrk-upload` (1634873, d1ab66e, de040fc, 5a626d3) into main as 38d1c66; `git merge-base --is-ancestor de040fc main` succeeds.
- Conflict in the TASK-254 ticket resolved to main's version, a superset of the branch copy. The untracked local TASK-253 ticket was a shorter summary of the branch copy and was set aside, not committed.
- Docker suite on 38d1c66: 2768 passed, 35 skipped, 13 tracked failures identical to the pre-existing set on 27d0e96 (tests/test_operations_render.py, tests/test_product_identity.py); tests/test_marc_tools_download.py passes. Host deploy tests 45 passed.
