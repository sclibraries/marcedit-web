# TASK-020 — Stream Tasks + Dedupe

**Status:** Completed
**Stage:** 20 (per `the-goal-of-this-sequential-sifakis.md` v3)

## Title

Stop materializing the full live record set as a single bytes blob in
the Tasks run loop and the Dedupe path. Both flows hold ~100 MB in
session state at 100K records today; Stage 20 routes them through the
on-disk RecordStore path with no per-batch in-memory copy.

## Scope

- `marcedit_web/lib/record_store.py`:
  * New `RecordStore.write_mrc_to(path)` — streams the live record
    sequence to a target file with one `pymarc.MARCWriter`, no
    intermediate `bytes` buffer. Returns the byte count.
- `marcedit_web/lib/sandbox.py`:
  * `run_tasks_subprocess` gains an optional `input_path=` kwarg.
    When supplied, the sandbox uses that file directly as the child's
    `--input`. When omitted, it falls back to the existing
    `record_bytes` path so the test corpus stays simple.
  * Mutually exclusive: supplying both is a ValueError.
- `marcedit_web/render/tasks.py`:
  * `_execute_sandboxed_run` writes the live store to
    `workdir/sandbox_input.mrc` via `store.write_mrc_to(...)` and
    passes the path to the sandbox. The intermediate `record_bytes`
    variable goes away.
- `marcedit_web/render/dedupe.py`:
  * On "Find duplicates", write the live store to a session-tmp
    `dedupe_buffer.mrc`. Keep the PATH in `st.session_state
    ["dedupe_buffer_path"]`; drop `st.session_state["dedupe_buffer"]`
    (the bytes blob).
  * Per-record render reads small slices via `open(path, "rb") +
    seek + read` rather than slicing a session-state buffer.
  * Export-deletes reads the path bytes ephemerally (gets GC'd after
    the export blob is built), still through
    `marc_diff.write_subset_to_bytes`.
- Tests:
  * `tests/test_record_store.py`: write_mrc_to round-trip + live-set
    (post-edit) round-trip.
  * `tests/test_sandbox.py`: input_path skips the in-memory write +
    mutually-exclusive validation.

## Out of scope

- Streaming the output side of the sandbox (the output mrc is bounded
  by the input cap and the user downloads it via `st.download_button`,
  which buffers anyway).
- A streaming variant of `marc_diff.write_subset_to_bytes` — the
  full-buffer build is fine ephemerally since it's not held in
  session_state across reruns.

## Success Criteria

1. `RecordStore.write_mrc_to(path)` writes the live record sequence
   to `path` and the result round-trips through `pymarc.MARCReader`
   with identical record count.
2. `run_tasks_subprocess(..., input_path=p)` runs successfully and
   uses `p` directly (no copy into workdir/input.mrc).
3. The Tasks run + Dedupe paths no longer hold the live record
   buffer in `st.session_state`. (Verified via inspection — pages
   reference paths, not bytes.)
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_record_store.py tests/test_sandbox.py
docker compose run --rm marcedit-web pytest -q
```
