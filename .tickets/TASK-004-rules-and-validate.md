# TASK-004 — Rules parser + validator + Validate page

**Status:** Completed
**Stage:** 4 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Build the parser for the extended `marc-rules.txt`, the rule-driven
record validator, and the first non-Home page (`pages/2_Validate.py`)
that surfaces the combined preflight + rules issue list.

## Scope

- `marcedit_web/lib/rules.py` — `parse_rules(path)` / `parse_rules_text(text)`
  return a `RuleSet` + a list of non-fatal `RulesParseWarning`s. Adds three
  additive directives to the existing format:
  * `####` field-level help on the heading line
  * `:help <text>` continuation, attaches to the most-recently-seen rule
  * `:byte <range> <label>` for control-field byte positions
  Dispatch on column 2 (`R`/`NR` vs anything else) distinguishes a real
  field block from a cross-record header (the file has both
  `245 1 One 245 must be present` AND `245 NR TITLE STATEMENT`).
- `marcedit_web/lib/rules_validate.py` — `validate_records(records, rules)`
  emits `Issue` codes: `rule-unknown-tag`, `rule-tag-nonrepeatable`,
  `rule-bad-indicator`, `rule-bad-subfield`, `rule-subfield-nonrepeatable`,
  `rule-length-mismatch`, `rule-only-one-1xx`, `rule-missing-245`.
  Cross-record `rule-cross-dedup` deferred to avoid double-reporting
  preflight's duplicate-001 check.
- `marcedit_web/pages/2_Validate.py` — Streamlit page combining
  `preflight.run_preflight` + `rules_validate.validate_records`; renders
  a filterable `st.dataframe` of issues with severity / code / record
  filters; surfaces rules-file parse warnings in a collapsed expander.
- `tests/test_rules.py`, `tests/test_rules_validate.py` — 30 new tests
  total.

## Success Criteria

1. `parse_rules(data/marc-rules.txt)` returns without raising and the
   shipped file produces the expected core tag entries (001, 008, 010,
   020, 856, etc.).
2. `:help` lines attach to the most-recent rule; multiple `:help` lines
   stack as paragraphs separated by `\n\n`.
3. `:byte` lines parse position-or-range correctly and attach via
   `:help` continuation.
4. Cross-record vs field-block dispatch on column 2 (R/NR vs other)
   correctly handles the dual 245 entries in the shipped rules file.
5. Unknown directives produce `RulesParseWarning` without aborting.
6. `validate_records` exercises every kept issue code via unit tests
   with deliberately-broken synthetic records.
7. The Validate page loads after upload, shows the four-metric summary
   (records / errors / warnings / info), filters by severity / code /
   record #, and surfaces the rules-file parse warnings in an expander.
8. `docker compose run --rm marcedit-web pytest -q` → all green.
9. `docker compose up -d` + Playwright drive Home → upload → click
   Validate in the sidebar → confirms metrics and table render.

## Verification result (2026-05-21)

- 30 new tests (22 rules + 11 rules_validate) added; pytest total now
  **129 passed in 0.27s** under Python 3.9-slim. Every issue code is
  exercised by a deliberately-broken synthetic record.
- The shipped `data/marc-rules.txt` parses end-to-end without aborting
  (verified by `test_full_marc_rules_file_loads_without_aborting`).
- Playwright smoke: Home → upload `sample.mrc` (7 clean records) →
  click sidebar `Validate` link → page shows `Records=7, Errors=0,
  Warnings=0, Info=1`, filter chips, dataframe chrome (Search /
  Download CSV / Fullscreen), all rendering correctly. The single
  info-level issue is the preflight `record-count` summary, which is
  the expected baseline for a clean file.
- Confirmed via a Docker-side `pymarc` scan that every tag in the
  fixture has a matching rule entry, so the zero-violation outcome is
  semantically correct, not a parser silent-skip.
- Caveat captured for later stages: hard browser navigation (i.e.
  full page reload) drops Streamlit session state. The sidebar
  page links use `pushState` and preserve state. Worth a follow-up if
  we want resumable URLs.

All nine success criteria satisfied.
