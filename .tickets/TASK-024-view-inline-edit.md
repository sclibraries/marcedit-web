# TASK-024 — View-page inline edit (100K-safe per-record edit)

**Status:** Completed
**Stage:** Post-v3 — direct user request.

## Title

MarcEditor's "all records as one Ace text buffer" model can't scale —
the existing 5K cap forces catalogers with a 100K-record batch to
chunk the file outside the app before they can review or edit
anything by hand. View is already 100K-safe (single-record render +
search + pagination); add per-record inline edit to it so the
cataloger has a real path for "open record N, look at it, fix one
thing, save."

## Scope

- `marcedit_web/render/view.py`:
  * New "Edit this record" button between the readonly `.mrk` block
    and the existing expanders.
  * Clicking opens an inline Ace editor pre-populated with the
    current record's `.mrk` text (rendered via the existing
    ``mrk_writer.render_records_mrk([record])``).
  * Save button: re-parse via ``mrk_parser.parse_mrk``, run
    per-record preflight + rule validation, block save on any
    fatal LineError code or any error-severity issue. On success,
    ``store.replace(index - 1, record)`` and reload the readonly
    view from the saved record.
  * Cancel button: drop the editor state, return to readonly.
  * Errors / warnings rendered inline beneath the Ace pane
    (collapsed when none).
- Session-state keys, namespaced to the View page:
  * ``view_edit_active`` — bool
  * ``view_edit_index`` — int (1-based)
  * ``view_edit_text`` — str (current buffer)
  * ``view_edit_parse`` — dict (last validation outcome)
- ``MAX_EDITOR_RECORDS`` semantics in MarcEditor stay unchanged.
  Add a one-line caption above its existing cap warning pointing
  catalogers at the View-page edit when they're over-cap.
- `tests/test_view_edit.py`: unit-shape tests for the parse+save
  helper that View will call. UI-shape tests stay light because
  Streamlit is hard to unit-test without a real script context.

## Out of scope

- A bulk subset-edit picker on MarcEditor. The user's stated need is
  "review and look at these records." Subset-edit is a future
  enhancement that can land separately if it's ever asked for.
- Cross-record find/replace on the View page. Tasks already covers
  programmatic transforms across the batch.
- Edit history / undo within the View edit pane. One save = one
  commit; the cataloger can re-edit to undo.

## Success Criteria

1. With a >5K-record batch loaded, the cataloger can navigate to any
   record in View, click Edit, mutate a field in Ace, click Save,
   and see the edit reflected on the next read of the same record.
2. A malformed edit (e.g. invalid `.mrk` line) blocks save with a
   visible error message; the buffer is preserved so the cataloger
   can fix it.
3. The 5K-cap warning on MarcEditor mentions View's inline edit as
   the path for large batches.
4. `pytest -q` stays green.
5. End-to-end Playwright run on `sample.mrc`: navigate to record 3,
   edit one subfield, save, navigate away and back — the edit
   survives.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_view_edit.py
docker compose run --rm marcedit-web pytest -q
```
