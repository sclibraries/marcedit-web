# TASK-028 — Scale Dedupe (and Home upload) to Diff-size workloads

**Status:** Completed
**Stage:** Post-v3 — direct user request.

## Title

TASK-027 unblocked the Diff page for multi-GB uploads. The cataloger
asked us to verify the Dedupe flow handles the same scale. Audit
shows two upstream caps and one in-memory step:

1. **Home upload cap** — `MARCEDIT_WEB_MAX_UPLOAD_BYTES` default
   250 MB. A 663 MB file fails at the Home upload step; the
   cataloger never reaches Dedupe.
2. **Session aggregate cap** — `MARCEDIT_WEB_MAX_SESSION_BYTES`
   default 1 GB. Several large uploads in one session blow it.
3. **Dedupe indexing memory spike** — `buf_path.read_bytes()` to
   feed `marc_diff.index_buffer` materializes the whole live store
   in memory. Same for export-deletes. Same shape Stage 27 just
   replaced with mmap on the Diff side.

## Scope

- `marcedit_web/lib/quotas.py`:
  * Bump `_DEFAULT_UPLOAD_BYTES` from 250 MB to 2 GB (matches the
    Diff per-file cap and the Streamlit framework cap in
    `.streamlit/config.toml`).
  * Bump `_DEFAULT_SESSION_BYTES` from 1 GB to 4 GB so a couple of
    multi-GB uploads in the same session don't trip the aggregate.
- `marcedit_web/render/dedupe.py`:
  * Replace `raw_bytes = buf_path.read_bytes()` indexing with
    `mmap.mmap(fh.fileno(), 0, access=ACCESS_READ)`. The mmap stays
    open for the duration of `index_buffer`; closed in `finally`.
  * Replace the export-deletes `source_bytes = buf_path.read_bytes()`
    block with the same mmap pattern. ``write_subset_to_bytes``
    reads only the records being exported, not the whole buffer.
- `docs/deployment.md`: update the env-var table to reflect the new
  defaults.

## Out of scope

- A streaming `write_subset_to_bytes`. The output is the subset of
  records being exported, bounded by `delete_candidates` × avg
  record size — fits in memory.
- Per-record render path — already path-based + seek-read since
  Stage 20.
- An `mmap`-aware refactor of `RecordStore.from_bytes` — the bytes
  are already in memory at that point (Streamlit's UploadedFile
  holds them); no extra copy to eliminate.

## Success Criteria

1. A 1.5 GB MARC upload succeeds via the Home page.
2. With that upload loaded, the Dedupe page builds the buffer and
   indexes via mmap — peak Python memory for the indexing pass is
   bounded by the touched OS pages, not the full file size.
3. Export-deletes completes through the mmap path.
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
```
