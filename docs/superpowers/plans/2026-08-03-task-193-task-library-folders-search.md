# TASK-193 Task-Library Folders and Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-193](../../../.tickets/TASK-193-task-library-folders-search.md)

**Goal:** Give catalogers a split personal/shared task library with safe folder organization and searchable task metadata while preserving task ownership, stable IDs, definitions, and execution behavior.

**Architecture:** Add an additive SQLite folder model and folder-aware task APIs in `task_db.py`; keep authorization and optimistic concurrency in the service layer. Build a normalized, revision-keyed search document from canonical definitions and safe parsed operation metadata, then render a split explorer in the Tasks page. Folder operations are transactional and never rewrite task bodies or native definitions.

**Tech Stack:** Python 3.9, stdlib sqlite3, Streamlit, existing `task_db`, `audit`, `task_builder`, `native_tasks`, pytest, authenticated browser tests.

## Global Constraints

- Existing private/shared visibility rules remain enforced before every list, search, count, and mutation.
- Shared task names are globally unique; personal names are unique per owner; migration reports conflicts and never renames silently.
- Maximum cataloger-created depth is three levels below each conceptual root.
- No `RETURNING`, recursive CTE, SQLite extension, or new dependency.
- Rename is an atomic in-place update preserving task ID, folder, created identity, and incrementing revision.
- Shared-folder mutations and cross-owner shared-task moves are audited.
- Older application code must tolerate the additive schema for rollback.

---

### Task 1: Add folder schema and idempotent migration

**Files:**
- Modify: `marcedit_web/lib/db.py`
- Test: `tests/test_db_migration.py`, `tests/test_task_db.py`

**Interfaces:**
- Consumes: current schema version 14 and `tasks` table.
- Produces: `task_folders` table, nullable `tasks.folder_id` during migration, personal/shared Unfiled roots, partial shared-name index, and schema version 15.

- [ ] **Step 1: Add failing migration tests** from pre-folder schemas covering private/shared tasks, repeated migration, historical shared-name conflicts, and rollback reads by the older schema.
- [ ] **Step 2: Implement additive DDL** without `RETURNING`, using explicit `ALTER TABLE`/index checks and one transaction.
- [ ] **Step 3: Implement migration preflight** that reports all shared-name conflicts with both owners and aborts before assigning folders when conflicts exist.
- [ ] **Step 4: Assign existing rows** to owner-specific personal Unfiled or global shared Unfiled and enforce the partial unique shared index only after conflict preflight passes.
- [ ] **Step 5: Run** `pytest -q tests/test_db_migration.py tests/test_task_db.py`; verify repeat migration is a no-op.
- [ ] **Step 6: Commit** `feat: add additive task-folder schema`.

### Task 2: Implement transactional folder/task-library APIs

**Files:**
- Create: `marcedit_web/lib/task_library.py`
- Modify: `marcedit_web/lib/task_db.py`
- Test: `tests/test_task_library.py`, `tests/test_task_db.py`

**Interfaces:**
- Consumes: schema from Task 1 and existing visible-task authorization.
- Produces: `list_folder_tree(user)`, `create_folder`, `rename_folder`, `move_folder`, `delete_empty_folder`, `move_task`, `rename_task`, `share_task`, `unshare_task`, and `search_visible_tasks` service APIs.

- [ ] **Step 1: Add failing authorization/concurrency tests** for personal folders, shared folders, cross-owner shared moves, stale revisions, inaccessible parents, and audit payloads.
- [ ] **Step 2: Add failing cycle/depth/nonempty-delete tests** that assert rollback leaves both folder and task rows unchanged.
- [ ] **Step 3: Implement bounded iterative parent walking** inside the same transaction; reject repeated IDs, missing parents, cross-scope parents, and depth > 3.
- [ ] **Step 4: Implement atomic task rename** with owner/expected-revision guard and in-place `UPDATE`; preserve ID, folder, created timestamp, and definitions.
- [ ] **Step 5: Implement visibility transitions** requiring a compatible destination; unshare defaults to the owner’s personal Unfiled folder.
- [ ] **Step 6: Run** `pytest -q tests/test_task_library.py tests/test_task_db.py`; inspect audit rows for actor, old/new path, and stable IDs.
- [ ] **Step 7: Commit** `feat: add transactional task-library organization APIs`.

### Task 3: Build safe task search indexing

**Files:**
- Create: `marcedit_web/lib/task_library_search.py`
- Modify: `marcedit_web/lib/task_db.py`
- Test: `tests/test_task_library_search.py`

**Interfaces:**
- Consumes: visible task rows, native definitions, parsed `# OP:` markers, folder paths.
- Produces: revision-keyed normalized search documents and deterministic filters for name, description, folder, owner, operation kind, tag, subfield, validation state, recent update, literals, and imported source name.

- [ ] **Step 1: Add failing tests** for every indexed field, all filters, case-folding, inaccessible private-task isolation, and malformed-task safe metadata fallback.
- [ ] **Step 2: Implement normalization** that never indexes generated Python, fingerprints, raw provenance, or private task content visible to another user.
- [ ] **Step 3: Add bounded cache invalidation** keyed by task ID/revision and folder path revision.
- [ ] **Step 4: Run** `pytest -q tests/test_task_library_search.py`; verify search does not require SQLite extensions.
- [ ] **Step 5: Commit** `feat: add safe task-library search indexing`.

### Task 4: Replace the Tasks list with the split explorer UI

**Files:**
- Modify: `marcedit_web/render/tasks.py`
- Create or modify: `marcedit_web/render/task_library.py`
- Modify: `marcedit_web/render/task_operation_cards.py` only for shared result-row rendering reuse
- Test: `tests/test_tasks.py`, `tests/test_task_library_render.py`

**Interfaces:**
- Consumes: Tasks page session state, Task 2 APIs, Task 3 search results.
- Produces: persistent collapsible My Tasks/Shared Tasks tree, breadcrumbs, global search/filter controls, compact results, focused folder/task dialogs, and editor return paths.

- [ ] **Step 1: Add failing render tests** for tree selection, search/filter state, empty folders, result visibility, shared-task read-only editing, and editor return to the same folder/search.
- [ ] **Step 2: Implement the split layout** with stable widget keys and no drag-and-drop requirement.
- [ ] **Step 3: Add focused create/rename/move/delete dialogs** that show clear conflict, depth, stale revision, and nonempty-folder errors.
- [ ] **Step 4: Wire sharing/unsharing to compatible folder selection** and show owner/audit-relevant status without exposing private content.
- [ ] **Step 5: Run** `pytest -q tests/test_tasks.py tests/test_task_library_render.py`; then run authenticated browser checks with a large fixture library.
- [ ] **Step 6: Commit** `feat: add split task-library explorer`.

### Task 5: Verify compatibility and close the ticket

**Files:**
- Modify: `.tickets/TASK-193-task-library-folders-search.md`
- Test: migration, API, search, render, browser, and Docker suites

- [ ] **Step 1:** Run the full supported Python 3.9 Docker suite and report all skips.
- [ ] **Step 2:** Exercise older-application reads against a migrated additive database fixture.
- [ ] **Step 3:** Request independent authorization, migration, search, and browser review; resolve all Critical/Important findings.
- [ ] **Step 4:** Update the ticket to `Completed` only after all criteria are evidenced and commit the ticket update.
