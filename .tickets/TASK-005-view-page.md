# TASK-005 — View page

**Status:** Completed
**Stage:** 5 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Build the first read-only page: `pages/1_View.py` shows the loaded
records as MarcEdit-style `.mrk` text with a record navigator and an
optional tag filter. Click-through help tooltips are a separate stage
(Stage 7).

## Scope

- `marcedit_web/pages/1_View.py`
  - Empty state when no file is loaded.
  - Record navigator: 1-based index input + Prev / Next buttons.
  - Banner showing record index, identifier (001 or first 035 $a),
    and title (245 $a, trimmed).
  - `.mrk` text rendered in a monospace `<pre>` block (or
    `st.code(text, language="text")`).
  - Optional tag filter: comma- or space-separated 3-char tags,
    parsed via `viewer.parse_fields`.
  - Sidebar: same status block as Validate.

## Out of scope

- Click-through tooltips on tags / byte positions (Stage 7).
- In-record editing (Stage 10).

## Success Criteria

1. Page renders empty state when no file is loaded.
2. After upload, the navigator shows "Record 1 of N" with identifier
   and title.
3. Prev / Next buttons advance the navigator without disrupting
   filter state.
4. Tag filter narrows the rendered `.mrk` to the selected fields
   (plus an optional `LDR` toggle).
5. `docker compose run --rm marcedit-web pytest -q` stays green.
6. Playwright drives Home → upload → click View → confirms the
   record renders.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: upload sample.mrc, click View, advance to record 3.
docker compose down
```

## Verification result (2026-05-21)

- `marcedit_web/pages/1_View.py` added. Reuses the existing
  `viewer.render_record`, `record_identifier`, `record_title`, and
  `parse_fields` helpers — no new lib code needed.
- Pytest still **129 passed in 0.28s** (the page is pure presentation;
  the underlying viewer surface is already covered by
  `tests/test_viewer.py`).
- Playwright smoke: Home → upload `sample.mrc` → click sidebar `View`:
  * sidebar showed `Loaded: sample.mrc / 7 records`;
  * navigator showed Prev (disabled), spinner=1, Next, "of 7";
  * banner showed `Record 1 of 7 — 1587455634 — Michelangelo
    Pistoletto`;
  * `.mrk` body rendered every field (LDR, 001, 003, 005, 006, 007,
    008, 020s, 040, 050, 100, 245, 264s, 300, 336/337/338, 504, 505,
    520, 588, 600, 650s, 700, 710, 776, 856) in monospace via
    `st.code(language="text")`.
  * Clicking Next ▶ advanced to record 2 (`1579014042 — On loss and
    absence`), Prev became enabled, and the rendered body changed.

All six success criteria satisfied.
