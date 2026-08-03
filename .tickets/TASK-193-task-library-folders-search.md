Title: Organize personal and shared tasks with folders and cataloger search

Parent: TASK-174

Design: [Task-library folders and search](../docs/superpowers/specs/2026-08-03-task-193-task-library-folders-search-design.md)

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
- Existing schemas migrate idempotently and rollback to the older application
  remains possible because the migration is additive.
- Authorization, migration, search, concurrency, and authenticated browser
  tests pass under the production Python/SQLite contract.

Status: Todo
