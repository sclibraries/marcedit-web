# TASK-027 — Diff page: stream uploads from disk, drop per-side aggregate cap

**Status:** Completed
**Stage:** Post-v3 — direct user request.

## Title

The original ``marc-diff`` CLI handled multi-GB file sets seamlessly by
streaming from disk. The Streamlit port loaded every uploaded file as
bytes into ``st.session_state``, doubling memory pressure (Streamlit
already holds the uploaded bytes in its own buffer), and a defensive
500 MB aggregate cap per side now blocks real cataloger workloads
(observed: 663 MB old + 654 MB new total). Re-introduce on-disk
streaming via mmap and drop the aggregate cap.

## Scope

- `marcedit_web/pages/6_Diff.py`:
  * ``_read_uploaded`` now writes each uploaded file to a per-session
    diff temp dir and returns ``list[(name, path_str)]`` instead of
    ``list[(name, bytes)]``. Per-file cap (env: ``MARCEDIT_WEB_MAX_DIFF_BYTES``)
    still applies. **The per-side aggregate cap is removed** — data
    lives on disk, not in Python memory.
  * New ``_open_buffers(paths_list) -> dict[name, BytesLike]`` opens
    each file as ``mmap.mmap`` so callers get a bytes-like view that
    only pages in the bytes actually read. Returns are kept alive by
    a small wrapper class so file handles + mmaps GC together.
  * All callsites that did ``dict(old_bufs)`` /
    ``dict(new_bufs)`` switch to ``_open_buffers``.
- `marcedit_web/lib/quotas.py`:
  * Default ``MARCEDIT_WEB_MAX_DIFF_BYTES`` bumped from 500 MB to
    2 GB to match Streamlit's framework cap. Per-file ceiling; env
    overridable as before.
- Audit: per-file accept/reject still logged. The aggregate ``upload-
  rejected reason=diff`` row is gone (the cap that produced it is
  gone).

## Out of scope

- A streaming variant of ``marc_diff.write_subset_to_bytes`` for the
  adds/deletes export. The output is bounded by the diff result, not
  by input size, so it fits in memory.
- Releasing Streamlit's own copy of the uploaded bytes. That's a
  framework constraint we can't change from the app side.
- Cross-stage refactor of ``marc_diff.index_buffers`` to accept paths
  directly. mmap gives us bytes-like compatibility for free.

## Success Criteria

1. Two-side upload of ~1.3 GB total succeeds (no aggregate cap fires)
   and runs through to the field-suggestion + diff steps.
2. Memory inspection inside the container shows ``diff_old_buffers`` /
   ``diff_new_buffers`` session-state entries are path strings, not
   bytes blobs.
3. Per-file cap still rejects a synthetic 3 GB file (above the 2 GB
   default).
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_quotas.py
docker compose run --rm marcedit-web pytest -q
```
