# TASK-006 — Report page

**Status:** Completed
**Stage:** 6 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Build `pages/3_Report.py`: high-level rollups across the batch (format
breakdown, tag counts, missing-field counts, URL-domain distribution)
plus a per-record summary table. Closes the user's original ask of
"both a high-level count and a per record count" so a cataloger can
quickly spot "which records are missing 856 links."

## Scope

- New page only. No lib changes — reuses
  `reporting.RecordSnapshot.of(record, index)` (already lifted in
  Stage 2) and Python `collections.Counter` for the aggregations.
- Section 1: "Across the batch"
  * Three metrics: total records, malformed, distinct tags seen.
  * Format breakdown (book / serial / database / video / audio /
    score / map / unknown) as a small bar chart + table.
  * Missing-field rollup with a tag multiselect; defaults to
    `001, 245, 856` per the spec. Output: "N of TOTAL records are
    missing TAG."
  * Top-N tag-count table (sortable).
  * Top-N URL-domain table from 856 $u.
- Section 2: "Per record"
  * `st.dataframe` with index, identifier, OCLC #, title, format,
    leader 06/07, tag count.
  * Search / sort comes from `st.dataframe`'s built-in chrome.

## Out of scope

- Click-through tooltips on tags (Stage 7).
- Drill-through to View page (interesting for v1.5; not a v1 blocker).

## Success Criteria

1. Empty state when no file is loaded.
2. Format breakdown chart + table render for the loaded batch.
3. Missing-field rollup with tag multiselect defaults to 001/245/856
   and shows the count of records missing each.
4. Per-record dataframe renders with id, title, format, leader,
   tag count.
5. `pytest -q` stays green.
6. Playwright drives Home → upload → Report and confirms numbers.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: upload sample.mrc, click Report, confirm format=book=7
# and per-record table has 7 rows.
docker compose down
```

## Verification result (2026-05-21)

- `marcedit_web/pages/3_Report.py` added. Reuses
  `reporting.RecordSnapshot.of` (no lib changes); aggregates via
  `collections.Counter`.
- Pytest: **129 passed in 0.43s** (page is pure presentation;
  reporting is already covered by `tests/test_reporting.py`).
- Playwright smoke: Home → upload `sample.mrc` (7 records) → click
  Report:
  * 3 metrics rendered: Records=7, Malformed=0, Distinct tags=37.
  * Format breakdown: Vega bar chart shows `book: 7`; companion
    dataframe shows the same.
  * Missing-field rollup defaulted to 001/245/856; dataframe renders
    counts.
  * Top tags + Top 856 URL domains side by side.
  * Per-record dataframe with index, identifier, OCLC #, title,
    format, leader 06/07, tag count.
  * Console: 0 errors, 13 warnings (Streamlit/Vega chrome only).

All six success criteria satisfied.
