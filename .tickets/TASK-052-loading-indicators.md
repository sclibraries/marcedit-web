# TASK-052 — Loading indicators on every long-running operation

**Status:** Completed
**Stage:** UX cleanup pass — visible feedback on every page.

## Addressed during pass

In addition to the scoped surfaces, the Report page's per-record
walk (``render/report.py`` aggregate loop) is also multi-second on
big batches and was wrapped in a spinner during this pass.

## Title

Several pages currently freeze silently while a slow operation runs
(upload parse, search, validation, conversions). Catalogers don't
know whether the page is doing anything or has hung. Wrap every
such operation in ``st.spinner(...)`` (single-phase) or
``st.status(...)`` (multi-phase with sub-step labels).

## Scope

Per the inventory in chat, these are the missing surfaces:

- **`marcedit_web/views/00_Home.py` — upload parse**
  ``session.handle_upload()`` parses the full ``.mrc``. Wrap the
  call with ``st.spinner("Parsing upload…")``. Re-render the
  summary banner after the spinner exits.
- **`marcedit_web/render/find.py` — search execution**
  ``search.matching_records_compound(store, queries)`` is fully
  synchronous. Wrap it with ``st.spinner("Searching…")``.
- **`marcedit_web/render/view.py` — search-as-you-type**
  ``search.matching_records(store, query)`` likewise. Same wrap,
  ``"Searching…"`` label.
- **`marcedit_web/render/validate.py` — preflight + rule validation**
  Two consecutive O(N) passes across the store; wrap both in a
  single ``st.status("Validating records…")`` with a "Preflight"
  → "Applying rules" → "Done" phase log so the user sees
  progress on big batches.
- **`marcedit_web/render/marc_tools.py` — conversions**
  All four converter entry points (``to_mrk``, ``to_mrc`` from
  MarcEdit/XML, ``to_marcxml``). Wrap each with
  ``st.spinner("Converting…")``. Audit row already fires after,
  unchanged.

While walking each render module, **also flag and wrap any other
multi-second op** discovered during edits — write them up in this
ticket's Out-of-scope→addressed list if they land.

Spinner messages are user-facing strings. Keep them present-tense,
verb-led, end with an ellipsis. "Parsing upload…" not "Upload
parsing in progress.".

## Out of scope

- Per-record progress bars. ``st.spinner`` / ``st.status`` is the
  right granularity for these operations; a per-record progress
  bar would re-render the script many times per second.
- Server-pushed progress updates for background tasks. The sandbox
  task runner already streams phase updates via ``st.status``;
  nothing else runs asynchronously.
- Skeleton loaders. Streamlit's spinner is the idiomatic answer.

## Success Criteria

1. Uploading a multi-MB ``.mrc`` on Home shows a "Parsing upload…"
   spinner for the duration of the parse.
2. Hitting "Search" on the Find page (and any subsequent re-search)
   shows the spinner until results appear.
3. Validate page shows a status block that walks Preflight →
   Rules → Done on a 1K-record batch.
4. Each Marc Tools conversion shows the spinner while the
   converter runs.
5. ``pytest -q`` stays green (no test logic changes; UI-only).

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
# Browser smoke: upload a sample .mrc and visually confirm the
# spinner appears on each surface above.
```
