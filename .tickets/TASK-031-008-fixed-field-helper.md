# TASK-031 — 008 Fixed-Field helper

**Status:** Completed
**Stage:** Second stage of MarcEdit Web v3.1 (after TASK-030).

## Title

The 008 control field is 40 bytes of position-encoded metadata that
catalogers edit constantly — date of cataloging, place of
publication, language, "form of item" (online vs print), audience
level, literary form, and so on. Today the cataloger has to count
bytes in the raw `.mrk` text. Add a structured editor that labels
each position, constrains allowed values, and writes the recomposed
40-byte string back to the record.

## Scope

- **Material types in scope for v1**: Books (BK) and Continuing
  Resources (CR). These cover roughly 80% of real cataloging
  records. Music (MU), Maps (MP), Visual Materials (VM), Computer
  Files (CF), and Mixed Materials (MX) are out of scope; the
  framework is data-driven so adding them later is a pure data
  PR.
- **New module** ``marcedit_web/lib/fixed_field_008.py``:
  * Position descriptors (label, byte range, allowed values, help
    text) for the shared positions (bytes 0–17, 35–39) plus
    material-specific positions (bytes 18–34).
  * ``material_type_for(record)`` — picks BK / CR / "other" from
    leader bytes 06 (type) + 07 (bib level).
  * ``parse_008(record)`` → ``list[FieldPosition]`` with each
    position's current value resolved against the record's
    material type.
  * ``apply_008(record, position_values: dict[str, str])`` →
    reconstructs the 40-byte ``008.data`` string and writes it
    back; raises ``ValueError`` on length / allowed-value
    violations BEFORE mutating.
- **New render helper** ``marcedit_web/render/fixed_field_helper.py``:
  * ``render_008_helper(record, store, index, *, key_prefix)`` —
    expander that lays out each position with the right widget
    (selectbox for enums, text_input for free-form). Save commits
    via ``store.replace(index - 1, record)`` after re-validating.
  * Same ``key_prefix`` pattern the single-record edit helper
    already uses, so View + Workspace Edit each get isolated
    session state.
- **Wired into**:
  * ``render/view.py`` — expander appears below the existing
    inline ``.mrk`` editor when the current record has an 008.
  * ``render/edit.py`` over-cap branch — same expander on the
    record-picker view.
- **Tests** ``tests/test_fixed_field_008.py``:
  * Material-type detection across leader byte combinations.
  * Position parse against the sample fixture.
  * Apply round-trip — set every BK position, recompose, parse
    back, assert match.
  * Length validation — apply with a too-short/too-long string
    raises ``ValueError`` and leaves the record untouched.
  * Allowed-value validation — apply with an enum violation
    raises before any mutation.

## Out of scope

- **Music / Maps / Visual / Computer Files / Mixed Materials**.
  Position descriptors are pure data; add in a follow-up.
- **LDR / 006 / 007 structured editors**. Same approach can be
  applied; defer to focused tickets.
- **Material-type-aware leader rewrite**. The 008 helper reads
  the leader to pick the material schema but doesn't write the
  leader. Catalogers who need to change record type continue
  using the `.mrk` editor.
- **Cross-record bulk apply**. The helper edits one record at a
  time, matching the existing single-record edit model.

## Success Criteria

1. With sample.mrc loaded → View record 1 → "008 Fixed-Field
   helper" expander present below the readonly .mrk block.
2. Open expander → each labeled position shows its current value
   from the record's 008.
3. Change a position (e.g. flip pos 23 form-of-item from `o` to
   ` `), click Save → readonly .mrk above refreshes with the new
   008.
4. Cancel doesn't write.
5. Same expander available on the Workspace Edit tab for batches
   over the 5K cap.
6. Records without an 008 show a friendly "no 008 field — add
   one in the inline editor" placeholder, not a crash.
7. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_fixed_field_008.py
docker compose run --rm marcedit-web pytest -q
```
