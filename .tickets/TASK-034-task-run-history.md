# TASK-034 — Task Run History

**Status:** Completed
**Stage:** Fifth stage of MarcEdit Web v3.1.

## Title

After a Tasks run, the cataloger sees one run's results
(``K_RUN_RESULTS`` in session_state). Reload the page or run again
and the previous run is gone. Add a per-session run history so the
cataloger can see what they did this session, re-download a prior
output, and look back at error counts.

## Scope

- **New helper** ``marcedit_web/lib/run_history.py``:
  * ``TaskRunRecord`` dataclass — timestamp, user, input filename,
    task names, record counts, changed count, error count,
    timed_out flag, sandbox returncode, input_path, output_path.
  * ``append_run(history, record, cap=5)`` — append + evict oldest;
    pure function over the history list, returns the (possibly
    smaller) updated history plus a list of records to clean up
    on disk. Unit-testable without Streamlit.
- **`render/tasks.py`**:
  * After ``_execute_sandboxed_run`` writes ``K_RUN_RESULTS``,
    also append a ``TaskRunRecord`` to
    ``st.session_state["task_run_history"]`` and clean evicted
    workdirs.
  * New ``_render_run_history()`` called after
    ``_render_run_results()`` — a collapsed expander listing each
    run (newest first) with: timestamp, tasks applied, records-
    in/out, changed-count, errors, two ``st.download_button``s
    (re-download input, re-download output) that read from the
    stored paths lazily so a 200 MB diff doesn't pin Python memory.
- **New audit event** ``task-run-completed`` — fires alongside the
  existing ``sandbox-timeout`` / ``sandbox-nonzero-exit`` events on
  every completed run (success or failure). Carries task names,
  record counts, changed count, returncode, timed_out.
- **Tests** ``tests/test_run_history.py``:
  * ``append_run`` under cap → no eviction.
  * ``append_run`` at cap+1 → returns evicted record list.
  * Run records are appended in chronological order.

## Out of scope

- **Persisted disk history** (across sessions). The user said
  "per-session or persisted" — pick the simpler one for v1.
  Persistence is a follow-up.
- **Per-run diff replay** inside the history expander. The pre-
  download diff review already lives on the current-run section;
  duplicating the full diff card list per historical run blows up
  the expander. The history entry shows summary counts; the
  re-download buttons let the cataloger pull the before/after
  pair into another tool.
- **Cross-user shared history** in prod (a "team activity feed").
  The audit log already captures that for ops eyes.

## Success Criteria

1. Running a task twice on the same batch shows BOTH runs in a
   "Run history" expander on the Tasks page.
2. Older-than-5 runs are evicted; the evicted workdirs are gone
   from disk.
3. Re-download buttons on a prior run yield a valid `.mrc`.
4. Each completed run adds a ``task-run-completed`` audit row.
5. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_run_history.py
docker compose run --rm marcedit-web pytest -q
```
