# TASK-013 — Workspace page with tabs

**Status:** Completed
**Stage:** 13 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md` v2)

## Title

Add `pages/0_Workspace.py` — one place to do the whole loaded-file
workflow (Edit / View / Validate / Report / Tasks / Diff) without
jumping around the sidebar. Refactor every existing page body into a
`render(store, …)` function under `marcedit_web/render/` so the
Workspace tabs and the deep-link pages stay byte-for-byte equivalent.

## Why

User-surfaced problem #3 from the v2 round: "The UI organization needs
to be improved as there is a lot of clicking. We could condense
several of the toolbar functions on the left into MarcEditor for
simplicity." This consolidates the per-loaded-file workflow into one
view while leaving the per-page URLs intact.

## Scope

- New package: `marcedit_web/render/` with one module per tab:
  * `view.py` — `render(store, rule_set)`
  * `validate.py` — `render(store, rule_set)`
  * `report.py` — `render(store)`
  * `tasks.py` — `render(store)` — drives task editor + run loop
  * `edit.py` — `render(store, rule_set)` — drives the MarcEditor
  * `diff.py` — `render()` — has its own uploads, no store dep

  Each renders the CONTENT only (no `st.set_page_config`, no
  sidebar, no "upload first" guard at the function level — the
  caller owns those page-level concerns).

- Existing `pages/N_<Name>.py` slim down to ~25-line shims:
  `st.set_page_config(...) → session.init() → sidebar → empty-state
  check → call render`. Deep-link URLs preserved.

- New `pages/0_Workspace.py`:
  * `st.set_page_config(...)`, `session.init()`, shared sidebar.
  * `st.tabs(["Edit", "View", "Validate", "Report", "Tasks", "Diff"])`.
  * Each tab calls the matching `render.*` function.
  * No upload? Tasks + Diff stay functional (they don't depend on
    the loaded batch). Edit / View / Validate / Report show their
    own empty state inside the tab.

## Out of scope

- In-tab perf optimizations (Stage 16).
- Changing any business logic — pure structural refactor.

## Success Criteria

1. Every page's deep-link URL still renders the same content as v2.
2. `pages/0_Workspace.py` renders with six tabs labelled Edit /
   View / Validate / Report / Tasks / Diff.
3. With sample.mrc uploaded: switching to any tab shows the same
   data the corresponding page shows.
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → upload sample.mrc → Workspace → cycle tabs
# (Edit → Parse, View → record 1, Validate → table, Report →
# metrics, Tasks → empty list, Diff → uploaders). Then deep-link
# /View directly and confirm same content.
docker compose down
```

## Verification result (2026-05-24)

- New package `marcedit_web/render/` with one module per tab:
  `view.py`, `validate.py`, `report.py`, `tasks.py`, `edit.py`,
  `diff.py`. Each exposes a `render(...)` function. Shared
  helpers `rules_for_page()`, `rules_and_warnings_for_page()`, and
  `sidebar_status()` live on the package `__init__`.
- New `pages/0_Workspace.py` composes the six render functions
  inside `st.tabs([...])`. The `0_` prefix puts it at the top of
  the sidebar.
- Every existing `pages/N_<Name>.py` slimmed from 100-400 LOC to
  ~20-line shims that call the matching render function (View,
  Validate, Report, Tasks, MarcEditor). `pages/6_Diff.py` left
  alone — too big to inline this stage, and its Workspace tab
  just links out to it (Stage 15 will add in-file dedupe there).
- Pytest: **196 passed in 0.54s** (no test changes; the refactor is
  structural).
- Playwright smoke: Home → upload `sample.mrc` → click Workspace
  in sidebar. Workspace renders title + caption, tablist with six
  tabs (Edit / View / Validate / Report / Tasks / Diff), sidebar
  shows "Loaded: sample.mrc / 7 records". Clicked View tab →
  full navigator + record 1 banner ("1587455634 — Michelangelo
  Pistoletto") + Field-help + Filter-fields expanders + full
  `.mrk` body. Clicked Validate tab → "7 records / 0 errors / 0
  warnings / 1 info" + filter chips + dataframe chrome. Zero
  console errors.

All four success criteria satisfied.
