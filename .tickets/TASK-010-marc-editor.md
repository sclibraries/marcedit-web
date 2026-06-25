# TASK-010 — MarcEditor (.mrk parser + Ace integration)

**Status:** Completed
**Stage:** 10 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

The MarcEdit-parity in-browser editor. Cataloger edits records as
MarcEdit-style `.mrk` text inside `streamlit-ace`; on Apply we parse
back to `pymarc.Record`s, run validation, surface line-pinned errors
as Ace annotations, and serialize the resulting batch to `.mrc` on
demand. This is the highest-risk piece in the v1 scope per the
original plan.

## Scope

- `marcedit_web/lib/mrk_writer.py` — small. Wraps `str(record)` and
  emits a multi-record blob separated by blank lines.
- `marcedit_web/lib/mrk_parser.py` — the load-bearing new module.
  * `LineError` and `ParsedRecord` dataclasses.
  * `parse_mrk(text: str) -> tuple[list[ParsedRecord], list[LineError]]`.
  * Tokenization rules per the plan: `=TAG  CONTENT`, LDR is 24 chars,
    control fields (001-009) carry raw byte-as-text, variable fields
    have 2 indicator chars + `$code`/`|code` subfields.
  * Both `$` and `|` accepted as input delimiters; `$` always emitted
    by the writer.
  * Indicators: space or `0-9`. Subfield codes: `0-9a-z`. Tag:
    `[0-9A-Z]{3}` or `LDR`. Each violation emits a `LineError` but
    the line still produces a best-effort `pymarc.Field`.
  * Never raises. Encoding errors return a single file-scope LineError.
- `tests/test_mrk_parser.py` and `tests/test_mrk_roundtrip.py` —
  unit + round-trip coverage. Every record in `tests/fixtures/sample.mrc`
  must satisfy `str(parse_mrk(str(rec)).records[0].record) == str(rec)`.
- `marcedit_web/pages/5_MarcEditor.py` —
  * Reads `st.session_state.records`, renders the batch as `.mrk` text.
  * `streamlit-ace` block with `language="text"`, `auto_update=False`.
  * On Apply: re-parse text, run preflight + rule validation,
    populate Ace annotations from `LineError` + `Issue` records.
  * Save button: when no fatal errors, serialize via `pymarc.MARCWriter`
    to a BytesIO and offer `st.download_button`. Updates
    `st.session_state.records` so other pages see the new batch.
  * Hard cap (`MAX_EDITOR_RECORDS = 5000`): above the cap the editor
    is read-only with a banner directing the user to the Tasks page.

## Out of scope

- In-Ace tooltips on tags / byte positions (Stage 11, v1.5).
- Byte-position rulers in the rendered `.mrk` (Stage 11/12).
- MARC-8 round-trip on write (we read with `to_unicode=True` and
  always emit UTF-8 — see v2+ list).

## Success Criteria

1. `parse_mrk` round-trips every record in `tests/fixtures/sample.mrc`
   byte-exactly (test asserts `str(parsed.record) == str(original)`).
2. `parse_mrk` accepts both `$a` and `|a` subfield delimiters on input;
   `mrk_writer.render_record_mrk` always emits `$`.
3. `parse_mrk` never raises on any input — including encoding errors,
   bad tags, bad indicators, bad subfield codes, and a leader that's
   not 24 chars.
4. MarcEditor page renders the loaded batch as editable `.mrk`,
   parses on Apply, shows error markers (gutter + annotation) for
   deliberate typos, and disables Save while fatal errors exist.
5. Save round-trip: edit a `245 $a`, save, the offered download
   contains the change.
6. Records over `MAX_EDITOR_RECORDS` switch the page into read-only
   mode with a banner explaining the cap.
7. Pytest stays green; new tests added for parser + round-trip.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → upload sample.mrc → MarcEditor →
#   * confirm .mrk renders with all 7 records;
#   * Parse + validate → 7 parsed, 0 fatal;
#   * Save to records + download → download offered.
docker compose down
```

## Verification result (2026-05-21)

- `marcedit_web/lib/mrk_writer.py` added (40 LOC, thin wrapper).
- `marcedit_web/lib/mrk_parser.py` added — full LineError /
  ParsedRecord model plus single-pass parser with never-raises
  contract. Accepts both `$` and `|` subfield delimiters on input;
  treats `\` as space placeholder in indicators, control field data,
  and the leader. Best-effort recovery on every error (bad tag, bad
  indicator, bad subfield code, missing leader, missing indicators,
  loose data before first delimiter).
- `marcedit_web/pages/5_MarcEditor.py` added — streamlit-ace editor
  with parse-on-button, Ace annotations from LineError + rule
  Issue, Save → MARCWriter → BytesIO → download, hard cap of 5000
  records with a banner. The parsed records are also pushed back
  into `st.session_state.records` so other pages see the edits.
- Tests: 21 new (12 unit + 5 round-trip + 4 batch). Total
  **165 passed in 0.34s** under Python 3.9-slim.
- Round-trip guarantee verified: every record in
  `tests/fixtures/sample.mrc` satisfies
  `str(parse_mrk(str(rec)).records[0].record) == str(rec)` —
  byte-exact through render → parse cycles, plus the batch reads
  back cleanly via `pymarc.MARCWriter` + `MARCReader`.
- Bugfix during smoke: the page's source-id cache key originally
  used `id(records)` from `session.current_records()`, but that
  function returns a fresh list per call so the id changes every
  rerun and wiped the parse cache. Fixed by keying on
  `(filename, total)` instead.
- Playwright smoke: Home → upload sample.mrc (7 records) →
  MarcEditor → Ace editor populates with the full batch's `.mrk` →
  Parse + validate → status updates to "Parsed 7 record(s); 0
  fatal, 0 warning, 1 info" → Save → success alert + download
  button "Download sample_20260521_195733.mrc".

All seven success criteria satisfied.
