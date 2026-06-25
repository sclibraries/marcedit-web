# TASK-043 — Dedupe at scale (progress + virtualized table + modal + keeper rules)

**Status:** Completed (see also TASK-044 for the regex-error visibility follow-up)
**Stage:** v3.2 cataloger workbench (after TASK-042).

## Title

Real cataloger workload: 10K records → 4K duplicate groups. The
current Dedupe page:

1. Indexes silently (no progress indicator).
2. Renders one ``st.expander`` per group → 4K expanders → browser
   lag.
3. Inspecting records means scrolling each expander; comparing two
   members of a group is awkward.
4. Keeper selection is per-group manual radios. At 4K groups,
   manual selection is infeasible, and the "first occurrence"
   default loses real cataloging signal: a second record with
   extra 035s (vendor IDs from multiple sources) is the keeper,
   not the first one indexed.

Fix all four together.

## Scope

### 1. Progress on indexing

Wrap the find-duplicates click handler in ``st.status("Indexing
records…")``. Steps inside the status block:

* "Building offsets index…" (the ``index_buffer`` pass).
* "Scanning N duplicate groups…" once results are in.

Closes the loop on the "what's the page doing for 8 seconds"
problem.

### 2. Virtualized results table

Replace the per-group ``st.expander`` loop with a single
``st.dataframe`` showing one row per duplicate group:

| key | size | keeper | identifiers (joined 001s) | strategy |

Streamlit's ``st.dataframe`` already virtualizes; rendering 4000
rows is a single component instead of 4000 components.

``on_select="rerun"`` + ``selection_mode="single-row"`` makes
clicking a row send the key back to the script; the script opens
a modal.

### 3. Diff modal

New ``@st.dialog("Compare duplicates", width="large")`` function
that, for one selected group, lays out the records side-by-side
using the existing ``marc_diff.field_diff`` machinery (same renderer
already used on the Diff page). A "Pick as keeper" radio at the
top of the modal lets the cataloger override the strategy choice
for THIS group.

### 4. Keeper-selection strategies

New ``marcedit_web/lib/dedupe_strategy.py``:

* ``KeeperStrategy`` enum:
  * ``FIRST_OCCURRENCE`` — current behavior; the default tie-break.
  * ``MOST_FIELDS`` — pick the record with the most total fields
    (a heuristic for "the richest record").
  * ``MOST_OF_TAG`` — pick the record with the most occurrences of
    a configured tag (e.g. "most 035s" — directly addresses the
    EDZ+SCSK example).
  * ``FIELD_MATCHES_REGEX`` — pick the record whose specified
    ``tag$subfield`` value matches the supplied regex; fall back
    to first occurrence if no member matches.
* ``pick_keeper(group_offsets, source_bytes, strategy, **kwargs)
  → offset`` — pure, unit-testable.
* ``apply_strategy_to_groups(dup_groups, source_bytes, strategy,
  **kwargs) → dict[key, offset]`` — runs the strategy across
  every group; returns a {group_key: keeper_offset} mapping.

UI: above the results table, a strategy selector + the
strategy-specific inputs (tag for MOST_OF_TAG; tag+subfield+regex
for FIELD_MATCHES_REGEX), plus an "Apply strategy" button that
re-evaluates keepers across all groups. The result lands in the
``keeper`` column of the dataframe.

Per-group manual overrides via the modal stay sticky in
session_state and are NOT clobbered by re-applying a strategy
(strategies pre-fill defaults; manual overrides win).

## Out of scope

- **Cross-record merge** ("combine 035s from all duplicates").
  Worth doing eventually but a separate workflow — not the
  "pick a keeper, delete the rest" model.
- **Multi-rule strategies** ("first try regex, then most-fields,
  then first"). Single-strategy ordering keeps the UI simple;
  per-group manual override handles edge cases.
- **Saving strategy configs** across sessions.
- **Streaming the strategy pass** to disk for very large duplicate
  sets — the current ``index_buffer`` already pulled the offsets
  into memory; strategy application is O(records-per-group) per
  group.

## Success Criteria

1. Clicking "Find duplicates" on a 10K-record batch shows a
   visible status block ("Indexing records…") until results land.
2. Page renders a single dataframe of duplicate groups, not 4000
   expanders. Browser scroll is smooth.
3. Clicking a group row opens a modal with side-by-side record
   diff. The modal has a "Pick as keeper" radio that overrides
   the strategy default for that group.
4. With strategy = ``MOST_OF_TAG`` (tag=035) on the user's
   reported scenario, the record carrying both EDZ + SCSK 035s
   is picked as keeper (not the EDZ-only first record).
5. With strategy = ``FIELD_MATCHES_REGEX`` (tag=035, sub=a,
   pattern=``^SCSK``), the SCSK record is picked.
6. ``pytest -q`` stays green; new tests cover every strategy.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_dedupe_strategy.py
docker compose run --rm marcedit-web pytest -q
```
