# TASK-045 — Sidebar reorganization via st.navigation

**Status:** Completed
**Stage:** v3.2 UX cleanup.

## Title

The sidebar is a flat alphanumeric list of 11 pages (Home,
Workspace, View, Validate, Report, Tasks, MarcEditor, Diff, Find,
Dedupe, Marc Tools). Catalogers asked for it to be grouped by
workflow so finding the right page isn't a scan. Switch to
Streamlit's ``st.navigation`` (1.36+) which supports named sections.

## Scope

- **Sections** (4):
  * **Start** — Home, Workspace.
  * **Inspect** — View, Find, Validate, Report.
  * **Edit** — MarcEditor, Tasks.
  * **Reconcile** — Diff, Dedupe, Marc Tools.
- **Entrypoint** (`marcedit_web/Home.py`): refactor to a pure
  navigation host. It registers every page via ``st.Page(...)``,
  builds the section dict, calls ``st.navigation(...).run()``.
- **New file** `marcedit_web/pages/00_Home.py`: the current
  Home.py content (file uploader + sidebar status + welcome).
  Numeric prefix is incidental — section order in
  ``st.navigation`` is what drives display.
- **Every `pages/*.py`**: drop the per-page
  ``st.set_page_config(...)`` call. ``st.set_page_config`` may only
  fire once per render; the entrypoint owns it now. ``st.Page(title=...)``
  carries the browser-tab title per page.
- **`.streamlit/config.toml`**: set ``client.showSidebarNavigation
  = false`` so Streamlit doesn't render the auto-discovered list
  alongside our grouped one.
- **URL preservation**: each ``st.Page`` gets ``url_path="View"``
  etc. so existing URLs (``/View``, ``/Tasks``) keep working.
- **Tests**: no new unit tests for this — it's a Streamlit-runtime
  wiring change. Live verification of each page loads + the
  sidebar shows the four sections.

## Out of scope

- **Renaming the underlying page files.** Number prefixes
  (``1_View.py``, etc.) become cosmetic; renaming for cleanliness
  would touch every import / Dockerfile reference and isn't worth
  the churn.
- **Per-section icons / colors.** Streamlit's section header
  styling is built-in; we keep the default.
- **Sidebar search.** Add later if catalogers start asking.

## Success Criteria

1. Browser sidebar shows four labeled sections in the order
   above, with the right pages under each.
2. Every page still loads (no ``set_page_config`` errors).
3. Direct URLs (``/View``, ``/Find``, ``/Dedupe``, etc.) still
   navigate to the right page.
4. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
```
