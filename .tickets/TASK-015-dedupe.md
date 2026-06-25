# TASK-015 — In-file duplicate detection

**Status:** Completed
**Stage:** 15 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md` v2)

## Title

Load one file, find duplicates within it, pick keepers, export
deletes. Closes user-surfaced problem #5 ("the diff is great but ...
we could load a mrc file and find all of the duplicate records too,
identifying which ones we want to keep and getting an export of
deletes").

## Why

The v1 Diff page only does two-file diff (original vs new). The
cataloger workflow also needs the in-file version: a single batch
arrives with accidental duplicates and the user wants to flag which
copy to keep and export everything else for deletion. The underlying
machinery is already in `lib/marc_diff.py` — `index_buffer` exposes
`duplicate_offsets` per match key — we just need the UI on top.

## Scope

- `marcedit_web/render/dedupe.py` (new) — `render(store)`:
  * Match-field config (one row, defaulting to OCoLC 035 $a).
  * "Find duplicates" button → calls
    `marc_diff.index_buffer("loaded", store.to_mrc_bytes(), specs)`
    and stashes the result in session state.
  * Per duplicate group: list the record offsets with a radio for
    keeper (default: first occurrence). Show each candidate's
    `.mrk` text via `pymarc.Record(data=buffer[off:off+length])` →
    `str(record)`.
  * "Export deletes" button → walk groups, collect every non-keeper
    location, run through `marc_diff.write_subset_to_bytes(...)`,
    offer a `.mrc` download.

- `pages/0_Workspace.py` — swap the Diff tab body so the Workspace
  has both two-file Diff (link out) and in-file Dedupe (inline tab).
  Cleanest: keep the existing Diff tab + add a 7th Dedupe tab.

- `pages/8_Dedupe.py` (new) — thin shim that calls
  `render.dedupe.render(...)` for the deep-link path.

- `tests/test_dedupe.py` — build a synthetic 5-record fixture with
  2 OCoLC duplicates. Assert:
  * `index_buffer(...)` surfaces one duplicate group of size 2.
  * Picking the first offset as keeper and running
    `write_subset_to_bytes(...)` on the other yields one record
    that reads back via `pymarc.MARCReader`.

## Out of scope

- Multi-field deduplication merge rules (e.g. "keep record with
  most subfields"). Manual radio selection only for v2.
- Bulk auto-keeper heuristics — defer.

## Success Criteria

1. With a fixture containing 2 OCoLC duplicates, the Dedupe page
   shows exactly 1 group of size 2.
2. After selecting a keeper, "Export deletes" offers a download
   button. Reading the download via `pymarc.MARCReader` returns
   the non-keeper record.
3. Workspace gets a "Dedupe" tab in addition to the existing Diff
   tab. Deep-link `/Dedupe` renders the same UI.
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → upload a dedupe-fixture.mrc with known
# duplicates → Workspace → Dedupe tab → "Find duplicates" →
# confirm group → select keeper → "Export deletes" → download.
docker compose down
```

## Verification result (2026-05-24)

- `marcedit_web/render/dedupe.py` (new, ~240 LOC) — full
  match-field config form, summary metrics, per-group keeper
  picker, deletes export. Reuses `marc_diff.index_buffer` and
  `marc_diff.write_subset_to_bytes` (no new lib code).
- `pages/8_Dedupe.py` (new) — thin shim around the render
  function, identical pattern to the other deep-link pages.
- `pages/0_Workspace.py` extended to 7 tabs: added a "Dedupe" tab
  next to "Diff" (Diff remains a link-out for two-file workflow).
- `tests/fixtures/dedupe-sample.mrc` (new, 776 bytes) — 5
  records, records #1 and #3 share OCoLC `111`; the rest are
  unique. Generated via a one-shot docker run with a
  writable mount.
- Tests: 6 new in `tests/test_dedupe.py` covering
  `index_buffer` group detection, offset ordering, write_subset
  yields only non-keepers, keeper choice affects export, and
  3-way duplicate groups → 2 deletes. Total **225 passed in
  0.42s** under Python 3.9-slim.
- Playwright smoke: Home → upload `dedupe-sample.mrc` →
  sidebar shows "5 records" → click Dedupe → match-field
  defaults to 035$a/(OCoLC)/strip → "Find duplicates" →
  metrics rendered: `035$a~(OCoLC)` / 5 records / 1 group /
  1 delete. Heading "Duplicate groups (1)" with an expandable
  "Key 111 — 2 record(s)" group. "Build deletes file" →
  success alert + "Download
  dedupe-sample_deletes_20260524_135019.mrc" download button.

All four success criteria satisfied.
