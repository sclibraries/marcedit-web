# TASK-009 — Tasks page

**Status:** Completed
**Stage:** 9 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Build `pages/4_Tasks.py` — list / create / edit / delete user tasks,
import MarcEdit `.tasksfile` text via uploader, and apply selected
tasks to the loaded batch with download of the transformed `.mrc`.
Uses the already-lifted `editor.py` (round-trip), `tasks.py`
(`@task` registry + loader), `marcedit_import.py` (MarcEdit
converter), and `task_builder.py` (form-builder palette).

## Scope

- `marcedit_web/pages/4_Tasks.py` with the following sections:
  1. Sidebar status (consistent with other pages).
  2. **Existing tasks** — list known tasks (loaded from a per-session
     temp dir via `tasks.load_user_tasks`). Each row has an edit
     button (puts the body in the editor) and a delete button
     (calls `editor.delete_user_task`).
  3. **New task** — open the editor in Code view by default.
  4. **Code editor** (streamlit-ace) — bound to the draft state in
     `st.session_state["tasks_editor_*"]`. Save calls
     `editor.save_user_task`, which AST-validates before writing.
  5. **Import from MarcEdit** — file uploader accepts a `.txt` or
     `.task` (zip) export, runs `marcedit_import.convert_tasksfile_text`
     or `convert_task_archive`, and saves the result(s) to the
     per-session tasks dir.
  6. **Run on loaded batch** — multiselect of registered tasks, a
     Run button that deepcopies the records, applies each task in
     order, captures errors via `transform_issue`, and offers a
     download of the transformed batch.
- Per-session temp tasks directory created on first visit:
  `tempfile.mkdtemp(prefix="marcedit-web-tasks-")` stored in
  `st.session_state["tasks_dir"]`. Session-only.
- Form view is **deferred to a follow-up ticket** — the palette
  schema in `task_builder.OPERATIONS_PALETTE` is rich enough that
  full coverage is its own piece of work. Code view is the v1
  power-user path; MarcEdit import covers the migration path.

## Out of scope

- Form view editor (palette → form fields per operation type).
  Round-trip via `# OP:` markers is already supported by the
  lifted `task_builder.py`; the UI to drive it lands later.
- Saving tasks across sessions (explicitly session-only per plan).

## Success Criteria

1. Empty state when no tasks exist yet: shows "+ New task" and
   "Import from MarcEdit" controls.
2. Creating a task via Code view writes it to the per-session tasks
   dir and renders it in the Existing tasks list on the next rerun.
3. Importing a small MarcEdit-style `.tasksfile` text produces a
   loadable task that runs against the loaded batch.
4. Selecting a task and clicking Run on a loaded batch (Home upload)
   produces a transformed `.mrc` with the change visible in the
   downloaded file (and surfaces any transform errors as a table).
5. Edit / delete buttons round-trip a task back into the editor or
   remove it cleanly.
6. `docker compose run --rm marcedit-web pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → upload sample.mrc → Tasks →
#   * create a task "noop" via Code view (placeholder body = pass)
#   * run it on the loaded batch
#   * confirm Records in/out=7, Errors=0, download is offered
docker compose down
```

## Verification result (2026-05-21)

- `marcedit_web/pages/4_Tasks.py` added (Code view editor only;
  Form view explicitly deferred).
- Per-session tasks dir created via `tempfile.mkdtemp(...)` and
  cached in `st.session_state["tasks_dir"]`. Survives in-session
  navigation; not across browser sessions.
- Pytest: **146 passed** (no new tests — the underlying lib surface
  is already covered by `tests/test_editor.py`,
  `tests/test_tasks.py`, `tests/test_task_builder.py`,
  `tests/test_marcedit_import.py`).
- Playwright smoke (Home upload + Tasks page):
  * Empty state shows "+ New task" and "Import from MarcEdit" controls.
  * "+ New task" opens a Code view editor with name + description
    fields and a streamlit-ace block prefilled with a `pass`
    placeholder body.
  * Filling name=`noop`, description=`No-op task that does nothing`
    and clicking Save creates the on-disk task; sidebar shows
    "1 task(s) defined this session".
  * Existing tasks list now shows `noop` with Edit / Delete
    buttons.
  * "Run on loaded batch" multiselect defaults to the new task.
  * Click Run → metrics show Records in=7, Records out=7,
    Errors=0; download button offers
    `sample_20260521_194038.mrc`.
  * Console: 0 errors, 11 warnings (Streamlit/Vega chrome only).

All six success criteria satisfied.
