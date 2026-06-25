# TASK-023 — Tasks UX: progress feedback + pre-download diff review

**Status:** Completed
**Stage:** Post-v3 — direct user request.

## Title

Two cataloger-facing UX gaps in the Tasks run flow:

1. **Progress invisible.** The current `st.spinner("Running tasks in
   sandbox...")` produces only the small top-right loading icon.
   Catalogers running 10K-record batches don't see whether the run is
   in flight, stalled, or already done.
2. **No verification step.** Today the cataloger goes straight from
   "Run" to a download button. They want to inspect what changed
   before exporting the new `.mrc` — confirming that the task did
   what they expected.

## Scope

- **Progress status block** in `render/tasks.py:_execute_sandboxed_run`:
  Replace `st.spinner(...)` with `st.status("Running tasks…",
  expanded=True)`. Inside, write one line per phase:
  "Reading N records from upload" / "Running task A" / "Running
  task B" / etc. On completion, update the label to a clear
  ✅ or ⚠️ marker and auto-collapse. A persistent caption above
  the run button warns "Working — please leave this tab open".
  Per-record streaming progress is out of scope (Streamlit blocks
  on the subprocess; can't poll concurrently without threading
  hacks that don't fit Streamlit's model).
- **Diff-review section** added between metrics and the download
  button. New module `marcedit_web/lib/task_diff.py`:
  * `compute_task_diff(input_path, output_path)` → `TaskDiffSummary`.
  * Pairs records by position (sandbox preserves order).
  * Fingerprints both sides (`marc_diff.fingerprint_record`) for the
    fast unchanged-row skip.
  * Computes `marc_diff.field_diff` only for records with a
    fingerprint change.
  * Aggregates per-tag counts: added / deleted / modified.
- `render/tasks.py:_render_run_results` adds:
  * Per-tag summary table (always visible).
  * A "X records changed, Y unchanged" line.
  * Collapsed expander "Show per-record diffs (X records)" with
    paginated diff cards inside. Cap at first 200 changed records;
    note the cap if it triggers.
- Diff cards render as side-by-side `=LDR` / `=NNN` lines with
  colored status markers (added / removed / changed / unchanged).

## Out of scope

- True streaming per-record progress (covered above).
- Re-running diffs on demand from the Diff page using the same input
  + output (the dedicated Diff page is the right tool for arbitrary
  pairings; Tasks-review is for "did this run do what I expected").
- Diff over very-large batches (>200 changes shows the cap).

## Success Criteria

1. After clicking Run, the status block is visible in-page with the
   work-in-progress label and per-task lines.
2. Once the run completes, the per-tag summary table renders with
   columns Tag / Added / Deleted / Modified.
3. The per-record drill-down is hidden behind a collapsed expander.
   Clicking it reveals the diff cards.
4. `compute_task_diff` returns the same diff summary regardless of
   whether the underlying batch was 7 records or 7000 (logic is
   per-record).
5. `pytest -q` stays green; new module covered by unit tests.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_task_diff.py
docker compose run --rm marcedit-web pytest -q
```
