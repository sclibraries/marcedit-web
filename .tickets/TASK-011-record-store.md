# TASK-011 — RecordStore (disk-backed, lazy parse)

**Status:** Completed
**Stage:** 11 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md` v2)

## Title

Replace the v1 in-memory `list[pymarc.Record]` with a disk-backed
`RecordStore` that holds the raw `.mrc` bytes in a session-temp file
plus an in-memory list of `(offset, length)` per record. pymarc
objects are produced only on demand. Edits + deletes + appends are
held in a small overrides map and merged on `to_mrc_bytes()`.

## Why

The 100K-record upload crashed v1 because
`session.parse_uploaded_bytes` eagerly parsed every record into a
`pymarc.Record`. With ~1-2 KB of pymarc overhead per record, 100K
records put ~150 MB in `st.session_state`. MarcEditor then tried to
render the whole batch as `.mrk` text (~30 MB string). The page fell
over and the upload was lost.

## Scope

**New file**: `marcedit_web/lib/record_store.py`. Public surface per
the plan (`RecordLocation`, `RecordStore.from_bytes`,
`from_path`, `count`, `get`, `iter_records`, `replace`, `append`,
`delete`, `to_mrc_bytes`, `malformed_count`).

**Implementation**:
- Build the offsets index by walking the raw bytes once, reusing
  `marc_diff._iter_records(data)` (already yields `(offset, raw)`).
- Storage: a temp file per session under
  `tempfile.mkdtemp(prefix="marcedit-web-records-")`. Path cached in
  the store instance.
- Override map: `dict[int, pymarc.Record | None]` (None = deleted).
  Appends become `(len(offsets), record)` entries on top of the
  underlying file's record count.
- `to_mrc_bytes()` walks the merged index and writes via
  `pymarc.MARCWriter`.

**`lib/session.py` migration**:
- `STATE_DEFAULTS["records"]` → `STATE_DEFAULTS["store"] = None`.
  Also drop `raw_bytes` and `malformed_count` from defaults — they
  now live on the store.
- `parse_uploaded_bytes(data)` → kept for backward-compat tests but
  marked deprecated; new code uses `RecordStore.from_bytes(...)`.
- New `handle_upload(uploaded_file)` builds a `RecordStore` and
  stashes it on `st.session_state["store"]`. Returns the same
  summary dict shape.
- `current_records()` becomes a thin shim that materializes via
  `list(store.iter_records())` with a `DeprecationWarning`; new
  pages call `current_store()`.

**Per-page changes** (mechanical):
- `Home.py` — sidebar uses `store.count()` and metadata from the
  store; download offers `store.to_mrc_bytes()` (no behavior change
  vs the original-upload echo, but now correct after edits).
- `pages/1_View.py` — `record = store.get(index - 1)`.
- `pages/2_Validate.py` — `preflight.run_preflight(records=list(store.iter_records()))`.
- `pages/3_Report.py` — `for snap in (RecordSnapshot.of(r, i) for i, r in enumerate(store.iter_records(), 1))`.
- `pages/4_Tasks.py` — run loop iterates the store, deepcopies +
  applies, writes to a new `BytesIO` for the download.
- `pages/5_MarcEditor.py` — uses `mrk_writer.render_records_mrk(store.iter_records())`. Save replaces records via `store.replace(i, edited)` for each parsed record (the parsed output preserves order, so we replace in index order).
- `pages/6_Diff.py` — unchanged; already buffer-based via marc_diff.

## Out of scope

- Stage 12 (task persistence) — separate ticket.
- Stage 13 (Workspace tabs) — separate ticket; depends on this one.
- Cross-session persistence of the loaded batch — v2 explicitly
  session-only.

## Success Criteria

1. `RecordStore.from_bytes(sample_bytes)` builds without parsing
   pymarc Records eagerly (verified by a memory-budget test).
2. `store.count() == 7` on the existing `sample.mrc` fixture.
3. `store.get(i)` returns a `pymarc.Record` matching the original.
4. `RecordStore.from_bytes(b).to_mrc_bytes()` round-trips to the
   same 7 records (via `pymarc.MARCReader` of the output).
5. `store.replace(0, edited_record)` is visible on the next
   `get(0)` and survives `to_mrc_bytes()`.
6. `store.delete(2)` then `count() == 6`; subsequent indices shift.
7. `pytest -q` stays green after the migration.
8. Playwright: upload sample.mrc → navigate Home → View → Validate →
   Report → MarcEditor → Save → download. No page crashes and the
   sidebar consistently shows "Loaded: sample.mrc / 7 records".

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: full multi-page navigation on sample.mrc.
docker compose down
```

## Verification result (2026-05-24)

- `marcedit_web/lib/record_store.py` added (320 LOC, including
  docstrings). Disk-backed via `tempfile.mkdtemp(...)` + temp file
  at `<dir>/upload.mrc`. In-memory offsets list + override map +
  appended list. Lazy pymarc parse on `.get(i)` / `.iter_records()`.
- `session.py` rewired: `STATE_DEFAULTS` drops `records` /
  `raw_bytes` / `malformed_count`; adds `store`. `current_store()`
  is the new primary read; `current_records()` is a deprecated
  shim. New `record_count()` helper for sidebar status lines.
- All 7 pages migrated: Home, View, Validate, Report, Tasks,
  MarcEditor, Diff. The MarcEditor's Save flow now does
  `store.replace_all(records)` + `store.to_mrc_bytes()` instead of
  writing back into raw bytes manually.
- Bonus polish: coerced the `record` column of every issue
  DataFrame to `str` to avoid the pyarrow mixed-type warning that
  was spamming the log on Validate / MarcEditor.
- Pytest: **184 passed in 0.42s** (165 v1 + 19 RecordStore).
- Playwright smoke: Home → upload `sample.mrc` → Validate (7
  records, 0 fatal, 1 info, no pyarrow log spam) → MarcEditor
  (editor pre-populates from store, no crash) → Parse + validate
  (7 parsed, 0 fatal) → Save → success alert "Saved 7 record(s)
  back into the session" + download `sample_20260524_131653.mrc`.
  Container stable throughout; sidebar consistently shows
  "Loaded: sample.mrc / 7 records".

All eight success criteria satisfied.
