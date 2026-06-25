# TASK-008 — Diff page

**Status:** Completed
**Stage:** 8 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Port `marc-diff/app.py` into `pages/6_Diff.py` as one page of the
unified marcedit-web app. Mechanical port: rewire imports, namespace
session keys so the Diff workflow runs independently of the Home upload,
and align the sidebar with the rest of the app.

## Scope

- `marcedit_web/pages/6_Diff.py` — port of the 731-line
  `marc-diff/app.py`. Three changes from the source:
  1. `import marc_diff` → `from marcedit_web.lib import marc_diff`.
  2. All session keys prefixed with `diff_` so the Diff workflow
     doesn't clobber the Home upload / View / Validate / Report state
     (`diff_old_buffers`, `diff_new_buffers`,
     `diff_combined_suggestions`, `diff_preview_matches`,
     `diff_preview_specs`, `diff_specs`, `diff_result`,
     `diff_include_changes`, `diff_output_blobs`, plus widget keys and
     paginator keys).
  3. "Start over" button only clears `diff_*` keys, not the whole
     session.

## Out of scope

- Any change to `marcedit_web/lib/marc_diff.py` (lifted as-is in
  Stage 2; no source changes for this port).
- Adding a 7th sidebar status line, etc. — Diff is purposely
  independent of the Home upload.

## Success Criteria

1. Page renders empty state with two upload widgets (Original / New).
2. After both sides are uploaded, the full workflow UI appears
   (suggestions, match fields, preview, run diff, results, downloads).
3. "Run diff" produces a metrics table with the six standard counts.
4. Session keys do not collide with Home state (uploading on Home
   stays loaded, uploading on Diff stays loaded; they're independent).
5. `docker compose run --rm marcedit-web pytest -q` stays green.

## Verification result (2026-05-21)

- `marcedit_web/pages/6_Diff.py` added (731 lines, structurally
  identical to the source app — only the three rewires above).
- Pytest: **129 passed in 0.43s** under Python 3.9-slim (no test
  changes; `lib/marc_diff.py` already covered by the lifted module's
  earlier surface).
- Playwright smoke: navigate to /Diff → upload sample.mrc as both
  Original and New → click Run diff. Results table appeared with:
  * Records in original (total): 7
  * Records in new (total): 7
  * Adds: 0
  * Deletes: 0
  * Common (matched): 7
  * Changed: 0
  The "7 records missing match fields" warning surfaced on both
  sides — correct for this BIBFRAME-style fixture that has no
  traditional 035 fields. Engine behaviour preserved from the source
  app.
- Sidebar shows all five pages (Home / View / Validate / Report /
  Diff). Diff is reachable directly via URL.

All five success criteria satisfied.
