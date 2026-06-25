# TASK-016 — Virtualization / perf polish

**Status:** Completed
**Stage:** 16 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md` v2)

## Title

Stream the Validate / Report aggregations so they don't materialize
the full record list per rerun. Closes user-surfaced problem #6 ("the
interface is slow when record counts are high"). Stage 11 already
bounded MEMORY via the RecordStore; this stage bounds CPU work too.

## Scope

- `lib/preflight.py:run_preflight` — accept any `Iterable[Record]`,
  not just `list[Record]`. Track total count via an internal counter
  instead of `len(records)`; replace the `not records` truthiness
  check with a "did we see any" sentinel.
- `lib/rules_validate.py:validate_records` — accept any
  `Iterable[Record]`. Already per-record under the hood; just relax
  the signature + drop the implicit list cast.
- `render/validate.py` and `render/report.py` — pass
  `store.iter_records()` directly instead of `list(...)`.
- Tests: existing suite must stay green. Add a small test that
  exercises the streaming path (pass a generator, not a list, to
  both functions).

## Out of scope

- Result caching keyed on store identity (`@st.cache_data` on heavy
  computations). Worth doing but it's a separate session-state
  invalidation design problem.
- Browser-level virtualization beyond what `st.dataframe` already
  provides. Streamlit's `st.dataframe` paginates internally.
- Synthetic 100K-record fixture + perf benchmarks. Hand the timing
  comparison to ops once we have a production batch to point at.

## Success Criteria

1. `run_preflight` accepts a generator and returns the same issues
   it would for the equivalent list.
2. `validate_records` accepts a generator and returns the same
   issues it would for the equivalent list.
3. Validate + Report tabs render correctly on the existing
   sample.mrc + dedupe-sample.mrc fixtures.
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → upload sample.mrc → Workspace tabs cycle
# (Validate / Report / Edit). Confirm no behavior regression.
docker compose down
```

## Verification result (2026-05-24)

- `lib/preflight.py` — signature now accepts `Iterable[Record]`.
  The function reorders to collect file-scope summary issues AFTER
  the per-record streaming pass (so we know the count without
  needing `len()`). File-scope issues prepend onto record-scope
  issues to keep the documented output ordering.
- `lib/rules_validate.py` — signature relaxed from `list[Record]`
  to `Iterable[Record]`. The body was already per-record so no
  logic changes.
- `render/validate.py` — both validators now receive
  `store.iter_records()` directly. The record-count metric reads
  from `store.count()` (offsets-based, O(1)) instead of from a
  materialized list.
- `render/report.py` — single-pass streaming loop builds the
  format/tag/url-domain Counters, the per-tag-presence Counter
  for the missing-field rollup, and a slim per-record-rows list.
  The full snapshot list is no longer retained — each
  `RecordSnapshot` falls out of scope immediately after its
  aggregate contributions are recorded.
- Tests: 5 new (`test_preflight.py`: generator-accept,
  list-vs-generator parity, empty-generator no-records,
  expected-count mismatch via generator; `test_rules_validate.py`:
  generator parity). Total **230 passed in 0.59s**.
- Playwright smoke: Home → upload `sample.mrc` → Validate via
  sidebar → identical 7/0/0/1 metrics and "1 of 1 issues shown".
  Report → "Across the batch" / Format breakdown / Missing-field
  rollup / Top tags / Per record table all render exactly as v2.

All four success criteria satisfied.
