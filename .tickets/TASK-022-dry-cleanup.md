# TASK-022 — DRY/SOLID cleanup

**Status:** Completed
**Stage:** 22 (per `the-goal-of-this-sequential-sifakis.md` v3)

## Title

Two surgical DRY wins:

1. A single shared "upload required" guard, replacing the six copy-paste
   `if not session.has_upload(): st.info(...)` blocks across the render
   modules.
2. Centralize the tasks-editor session-state key names as constants at
   the top of `render/tasks.py` so a typo is caught at import time
   instead of becoming a silent state-leak bug.

## Scope

- `marcedit_web/lib/session.py`:
  * Add `require_upload(blurb)` that renders the standard
    "Upload a `.mrc` file on **Home** to {blurb}." banner and returns
    `False` when no file is loaded, `True` otherwise.
- `marcedit_web/render/{view,validate,report,edit,dedupe,tasks}.py`:
  * Replace each `if not session.has_upload(): st.info(...); return`
    block with `if not session.require_upload(...): return`.
- `marcedit_web/render/tasks.py`:
  * Add module-level constants for every `tasks_editor_*` /
    `tasks_run_results` session key. Replace every literal-string
    reference with the constant.
- `tests/test_session_require_upload.py`: small unit covering
  has-upload → True / no-upload → False + banner emitted.

## Out of scope (and why)

- **Splitting `marcedit_web/lib/marcedit_import.py`.** The file is 734
  lines but already organized into clear sections (condition
  translation, .mrk parse, operation handlers, top-level conversion,
  archive handling, file rendering) with `# ----` separators. A 4-file
  split would re-locate code without reducing the underlying
  complexity. Not worth the import-graph churn or the file-jumping it
  costs reviewers.
- **A dataclass wrapper around the tasks-editor session state.**
  Streamlit's rerun model means a class-based wrapper would re-read
  state from `st.session_state` on every property access anyway —
  same work, more indirection. Constants give us 90% of the
  typo-resistance benefit at 10% of the complexity.
- **Centralized session keys across feature modules.** Each feature
  already namespaces its keys (`diff_*`, `dedupe_*`, `tasks_*`).
  Pulling them into one global dict couples every feature to a single
  registry without making bugs less likely.

## Success Criteria

1. `grep -rn "if not session.has_upload" marcedit_web/` returns no
   matches.
2. `grep -rn "Upload a .mrc file" marcedit_web/` returns at most one
   match (the new banner inside `session.require_upload`).
3. `grep -n "tasks_editor_open" marcedit_web/render/tasks.py` only
   references the constant, never the literal string.
4. `pytest -q` stays green.
5. The Tasks page exercises the same flow (new task, save, run)
   it did before refactoring.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_session_require_upload.py
docker compose run --rm marcedit-web pytest -q
```
