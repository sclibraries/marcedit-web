# TASK-007 — Help tooltips on View

**Status:** Completed
**Stage:** 7 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Add a click-through help lookup to the View page, backed by the
extended `marc-rules.txt`. Closes the user's stated need: "the
character `i` is in leader position 28 — what does that mean?" The
help text travels with the rules file (single source of truth) so
maintaining it is one edit per directive.

## Scope

- `marcedit_web/lib/help_lookup.py` — `help_for(rules, *, tag,
  subfield=None, byte=None) -> HelpEntry | None`. Resolution order:
  byte position → subfield → field heading.
- `marcedit_web/lib/tooltips.py` — small Streamlit-side wrapper that
  formats a `HelpEntry` as markdown (title + body + source).
- `pages/1_View.py` — adds a "Field help" expander above the `.mrk`
  rendering with three controls: tag selectbox (current record's
  tags ∪ LDR), optional subfield code text input, optional byte
  position number input. Resolves on every rerun and shows the
  resulting `HelpEntry` (or a graceful "no entry yet" message).
- `data/marc-rules.txt` — adds an `LDR` field block and `:byte` /
  `:help` continuations on 008 to demonstrate the directives end-to-
  end. The shipped marc-processing rules file had no LDR or
  byte-position coverage, so this is greenfield content.
- `tests/test_help_lookup.py` — covers each resolution path.

## Out of scope

- Per-field inline popovers (would require breaking the `.mrk`
  rendering into individual components per field — bigger UI work
  not aligned with the v1 scope). The plan's user-facing description
  was met with the help-lookup panel.
- Help-on-MarcEditor (the Ace integration tooltips) — that's the
  separate v1.5 stage 11.

## Success Criteria

1. `help_for(rules, tag="245")` returns a HelpEntry with the 245
   field heading and any `####` help.
2. `help_for(rules, tag="245", subfield="a")` returns the subfield
   entry's label + help.
3. `help_for(rules, tag="008", byte=28)` returns the BytePos covering
   28 with its label + accumulated `:help`.
4. `help_for(rules, tag="LDR", byte=6)` returns the LDR byte-position
   entry.
5. Unknown lookups return `None`; the View page surfaces this as
   "no entry in marc-rules.txt" rather than an error.
6. View page renders the new "Field help" expander, defaults to the
   first tag in the current record, and updates the displayed help
   in-place as the user changes inputs.
7. Pytest stays green; new tests added for help_lookup.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: upload sample.mrc, click View, expand "Field help",
# set tag=008 and byte=28, confirm the rendered help mentions
# "Government publication".
docker compose down
```

## Verification result (2026-05-21)

- `marcedit_web/lib/help_lookup.py` and
  `marcedit_web/lib/tooltips.py` added. Resolver is Streamlit-free
  and unit-tested.
- `data/marc-rules.txt` extended with an LDR field block plus
  `:byte` / `:help` directives on both 008 (positions 0-5, 6, 7-10,
  11-14, 15-17, 23, 28, 35-37, 38, 39) and LDR (positions 5, 6, 7,
  8, 9, 17, 18, 19). The directives are additive — no existing
  fields disturbed.
- `pages/1_View.py` adds a "Field help" expander above the `.mrk`
  rendering with tag (selectbox of LDR + record tags), subfield
  code (text input; disabled for control fields), byte position
  (text input; disabled for variable-data fields), and a Clear
  button. The help body renders as markdown below the controls.
- Tests: **146 passed in 0.30s** (17 new help_lookup tests).
- Playwright smoke: Home → upload sample.mrc → click View →
  expand "Field help" → default LDR field-level help renders →
  select 008 from the tag dropdown → field-level 008 help renders
  → type `28` into Byte position → help updates to "008 byte 28 —
  Government publication" with the full enum including
  `'i' = international intergovernmental`. The user's exact
  example case works end-to-end.

All seven success criteria satisfied.
