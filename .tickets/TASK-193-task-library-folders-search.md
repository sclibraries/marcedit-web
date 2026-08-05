Title: Organize personal and shared tasks with folders and cataloger search

Parent: TASK-174

Design: [Task-library folders and search](../docs/superpowers/specs/2026-08-03-task-193-task-library-folders-search-design.md)

Navigation Addendum: [Task workspace navigation and dialog usability](../docs/superpowers/specs/2026-08-05-task-193-task-workspace-navigation-design.md)

Scope:
- Add stable personal and collaborative shared folders with three levels below
  each root.
- Replace the single task list with a split folder explorer and searchable,
  filterable task results.
- Migrate existing tasks transactionally into personal or shared Unfiled
  folders without rewriting task definitions.
- Preserve task ownership and prevent duplicate task names within either a
  personal library or the shared library.

Success Criteria:
- Every signed-in cataloger may create, rename, move, and organize shared
  folders; all shared-folder mutations are audited.
- Any signed-in cataloger may edit a shared task while its owner and shared
  visibility remain unchanged; edits use optimistic revisions and are audited.
- Nonempty deletion, cycles, depth overflow, stale revisions, and inaccessible
  parents fail with clear messages and no partial writes.
- Sharing requires a shared destination; unsharing defaults to the owner's
  personal Unfiled folder; moving never changes ownership or content.
- Search covers visible task metadata and cataloger-meaningful operation
  content without exposing private tasks, generated Python, or fingerprints.
- Existing shared-name conflicts are reported before migration and must be
  resolved explicitly; migration never silently renames a task.
- Task rename preserves the stable task ID, folder, and history and increments
  the existing revision atomically.
- Conceptual `Unfiled` roots remain stable anchors and cannot be renamed, moved,
  or deleted.
- Run, Library, Create, and Import use URL-synchronized tab-style navigation;
  browser Back and Forward restore tabs, folders, filters, and authorized
  dialog targets without discarding session-scoped drafts.
- Folder creation is a prominent, explicitly labeled Library action, and every
  task-library modal has a visible Cancel or Close action in success and error
  states.
- Existing schemas migrate idempotently and rollback to the older application
  remains possible because the migration is additive.
- Authorization, migration, search, concurrency, and authenticated browser
  tests pass under the production Python/SQLite contract.

Implementation checkpoint:
- Folder APIs, stable in-place rename, visibility authorization, cataloger
  search filters, and the split task-library explorer are implemented.
- Shared task edits now retain the original owner/folder, enforce optimistic
  revisions, and record the acting cataloger; sharing, unsharing, and deletion
  remain owner-only.
- Non-admin edits of shared hand-written tasks preserve the existing body and
  imports; adding typed operations to such a task fails closed instead of
  replacing its code with an empty generated body.
- Native-definition edits in the Tasks form now round-trip only through the
  supported v1 subset (delete tag, sort fields, and structured build field);
  unsupported operations fail closed instead of degrading to legacy storage.
- Shared-task collaborators can edit content but cannot rename the owner’s
  task; the storage APIs and editor enforce the same boundary for legacy and
  native definitions.
- Schema v17 adds dedicated case-insensitive unique indexes for shared and
  personal Unfiled roots, including databases upgraded from schema v16.
- Native rename conflicts now fail with the same cataloger-facing duplicate
  name error as hand-written tasks and leave both rows unchanged.
- Shared/private organization actions remain audited and task deletion is
  preserved in the explorer.
- Focused Python tests pass. The Python 3.9 hotfix Compose suite passes with
  2,515 tests passed and 18 explicit environment/corpus skips. Authenticated
  browser verification remains outstanding.

Task 6 verification (2026-08-05):
- Added the cataloger-facing [Tasks workspace guide](../docs/task-workspace.md)
  and linked it from the README Tasks section.
- Added a runtime capability test asserting that the Streamlit segmented
  control exposes `options`, `selection_mode`, `key`, and `on_change`.
- The exact focused TASK-193 suite passes in the Python 3.9 hotfix Compose
  container: 445 passed, 0 failed, 0 skipped. The host Python 3.14 run has
  442 passed and three existing raw-regex subprocess failures caused by its
  `ModuleNotFoundError: marcedit_web` import-path mismatch.
- Final navigation/dialog changes were rechecked in the authoritative Python
  3.9.25 / Streamlit 1.50.0 hotfix Compose run: 2,599 passed, 0 failed, and
  five explicit skips (four Docker-CLI-in-container Compose-render checks and
  one unavailable institutional task corpus).
- The earlier Task 6 checkpoint run passed 2,592 tests with the same five
  explicit skips. Four parameterized Compose-render tests skip because the
  Docker CLI is unavailable inside the test container; the institutional
  task-corpus classification test skips because that corpus is not mounted and
  synthetic fixtures remain authoritative.
- `git diff --check` and `python3 -m compileall -q marcedit_web tests` both
  exit 0. Full evidence is recorded in the local Task 6 report.
- Authenticated browser acceptance and final code review are not available in
  this worktree, so this ticket remains In-Progress.

Status: In-Progress
