# TASK-035 — Post-v3.1 review fixes

**Status:** Completed
**Stage:** Post-v3.1 review follow-up (after TASK-030 — TASK-034).

## Title

Five findings surfaced by the v3.1 review:

1. **Medium** — Run-history download buttons re-read large files on
   every Tasks-page render because Streamlit evaluates collapsed
   expander contents. Add a "Prepare download" gate per history row
   so bytes are only loaded when the cataloger asks.
2. **Low/Medium** — ``TaskRunRecord.changed_count`` and the
   ``task-run-completed`` audit both record 0; the diff that
   produces the real number is computed lazily by the diff review.
   Compute it eagerly during ``_execute_sandboxed_run`` and thread
   it into both surfaces.
3. **Low/Medium** — Marc Tools session source serializes the live
   batch on render. Defer to the Convert click.
4. **Low** — Marc Tools upload audit fires on every page rerun.
   Move accept-emission into the Convert handler so it fires once
   per actual conversion attempt; reject still fires immediately.
5. **Security follow-up** — MARCXML import hands the uploaded bytes
   straight to ``pymarc.marcxml.parse_xml_to_array``. Add a byte-
   scan defense that rejects ``<!DOCTYPE`` and ``<!ENTITY``
   declarations before parsing — cheap, no dep, blocks the obvious
   billion-laughs / XXE shapes.

## Scope

- `render/tasks.py`:
  * History download buttons → "Prepare download" two-step using
    a session-state ready-flag per row.
  * `_execute_sandboxed_run` now builds the `TaskDiffSummary`
    immediately after the sandbox returns, stores it on
    ``K_RUN_RESULTS["_diff_summary"]`` (so the renderer reuses it
    instead of rebuilding), AND uses its ``changed_count`` /
    ``unchanged_count`` for the audit + history record.
- `render/marc_tools.py`:
  * `_binary_source` returns a small dataclass with a deferred
    ``materialize() -> bytes`` callable; the Convert handlers call
    it inside the button-click branch.
  * `_check_upload` splits into a render-time check (reject + show
    error) and a convert-time audit emission (only fires on Convert
    click).
- `lib/converters.py`:
  * `to_binary_from_marcxml` rejects DOCTYPE / ENTITY declarations
    in the first 4 KB of input via a case-insensitive byte scan.
    Raises ``ValueError`` with a clear message before pymarc sees
    the bytes.
- Tests:
  * `tests/test_run_history.py` already covers cap logic — no
    changes needed for the cap behavior.
  * `tests/test_converters.py` — new test asserting MARCXML with
    a DOCTYPE is rejected; new test asserting MARCXML with an
    ENTITY declaration is rejected; existing happy-path test
    confirms normal MARCXML still parses.

## Out of scope

- **defusedxml dependency.** Byte-scan defense covers the
  practical cataloger workload. A full defusedxml integration is
  worth doing if MARCXML import becomes a broadly-exposed surface,
  but it's a follow-up.
- **Conditional history download (size threshold)** — the
  prepare-button gate covers every row uniformly, which is
  simpler than tracking a size threshold.

## Success Criteria

1. Opening the Tasks page after several runs does NOT call
   `read_bytes` on any history workdir (verified by reviewing
   ``_render_history_entry`` — it now only reads when the prepare
   button has been clicked for that row).
2. A completed run's `task-run-completed` audit row carries a
   non-zero `changed_count` when the run actually changed records.
3. Opening Marc Tools with a 100K-record session batch loaded does
   NOT serialize the batch to bytes; opening the page is
   render-only-cheap.
4. Switching Marc Tools target / source radios does NOT add a new
   `upload-accepted` audit row each time.
5. Uploading a MARCXML file containing `<!DOCTYPE` raises a
   user-visible error before pymarc parses it.
6. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_converters.py
docker compose run --rm marcedit-web pytest -q
```
