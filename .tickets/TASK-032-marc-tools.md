# TASK-032 — Marc Tools conversion hub

**Status:** Completed
**Stage:** Third stage of MarcEdit Web v3.1 (after TASK-030 ops + TASK-031 008 helper).

## Title

MarcEdit's "MARC Tools" is the entry point catalogers reach for when
they need to convert between `.mrc`, `.mrk`, and MARCXML, or pull a
quick tabular view of a batch. Today marcedit-web has the parser /
writer plumbing scattered across pages but no single conversion
surface. Add a dedicated page with four conversion targets:
`.mrc` binary, MarcEdit `.mrk`, MARCXML, and CSV preview/export.

## Scope

- **New page** `marcedit_web/pages/9_MarcTools.py` — alphanumeric
  ordering places it last in the sidebar (after Dedupe). Top-of-page
  radio picks the target format; the form below changes accordingly.
- **New render module** `marcedit_web/render/marc_tools.py`:
  * `render_marc_tools()` — entry point called by the page.
  * Internal helpers per conversion (`_convert_to_mrk`,
    `_convert_to_binary`, `_convert_to_xml`, `_render_csv`).
- **New lib module** `marcedit_web/lib/converters.py`:
  * `to_mrk_text(record_bytes)` — binary MRC → MarcEdit `.mrk`.
  * `to_binary_from_mrk(text)` → binary, plus `LineError` list.
  * `to_marcxml(record_bytes)` — binary → MARCXML string.
  * `to_binary_from_marcxml(xml_text)` → binary, plus issues.
  * `records_to_csv_rows(record_iter, columns)` — flatten records
    to a list of dicts; CSV writing happens in the renderer with
    `csv.DictWriter`.
  * Default CSV columns (cataloger-facing display set):
    `001`, `008_date_1`, `100_a`, `245_a`, `245_b`, `260_a`,
    `260_b`, `260_c`, `020_a`, `022_a`, `856_u`.
- **Sources** for each conversion: file upload (uploader scoped to
  the source format's extensions) OR "use loaded session batch"
  when one is loaded. Empty source → page stays informational, no
  action.
- **Audit**: each successful conversion emits
  `conversion-issued` with kind, source-bytes count, output-bytes
  count, source ("upload" or "session").
- **Preflight info** displayed before download: record count
  (parsed cleanly), malformed count (skipped by pymarc), encoding
  note (UTF-8 only).
- **Tests** `tests/test_converters.py`:
  * Binary → mrk round-trips identifier + selected subfield.
  * mrk → binary round-trips back to identifier; `LineError`s
    bubble up.
  * Binary → MARCXML produces well-formed XML with `<record>` /
    `<datafield>` / `<subfield>` elements.
  * MARCXML → binary round-trips identifier.
  * CSV rows pull the default columns; missing fields → empty cell;
    multi-subfield values are joined.

## Out of scope

- **MARC-8 encoding.** The project is UTF-8 only (per the v2 plan).
- **MARCBreaker / MarcMaker variants.** MarcEdit's `.mrk` is the
  canonical pymarc shape; other historic mnemonic formats deferred.
- **Round-trip fidelity tests across all four formats.** Per-pair
  tests cover the contract; a full cross-product matrix is its own
  ticket.
- **Streaming converters.** Each conversion materializes the
  result in memory because the result becomes a `st.download_button`
  payload anyway. Same quota story as TASK-019 — file caps remain
  the upper bound on input size.

## Success Criteria

1. Sidebar shows "MarcTools" as a navigable page.
2. With sample.mrc loaded, picking each of the 4 targets and
   "Use loaded session batch" produces a downloadable result.
3. Uploading a `.mrk` and converting to `.mrc` round-trips through
   `pymarc.MARCReader` as the same record count.
4. CSV preview renders a `st.dataframe` with the default 11
   columns and one row per record.
5. Each conversion adds a `conversion-issued` row to the audit log.
6. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_converters.py
docker compose run --rm marcedit-web pytest -q
```
