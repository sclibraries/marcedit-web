# TASK-026 — Human-readable MARC display in View

**Status:** Completed
**Stage:** Post-v3 — direct user request.

## Title

The current `.mrk` view double-encodes the actual MARC content for
display: every space in a control field renders as `\` (MarcEdit's
convention for "blank space"), and the subfield delimiter is `$`
which collides with `$` characters that legitimately appear in
subfield values. The cataloger asked for the View to "properly handle
pipes and subfields and not just special encode the display." Replace
the display-side renderer with one that walks the raw MARC bytes:
spaces stay spaces, pipes stay pipes, the subfield delimiter (byte
0x1F) shows as `‡` (double dagger) so it's visually unambiguous.

## Scope

- New `viewer.render_record_human(record, fields=None)`:
  * Reads raw bytes via `record.as_marc()`.
  * Walks the directory via the existing `marc_diff._iter_directory`
    + `_field_bytes` helpers.
  * Emits one line per field, `=NNN  data` shape, with byte 0x1F
    replaced by `‡` so subfield delimiters are visible.
  * Honors a `fields` filter on the same shape as the existing
    `render_record`.
- View page (`render/view.py`) switches to `render_record_human` for
  the readonly record block.
- Workspace Edit tab over-cap preview (`render/edit.py`) switches to
  `render_record_human` too.
- Existing `viewer.render_record` stays — it's the `.mrk`/pymarc-str
  shape the parser round-trips and may be used in other contexts.
- `tests/test_viewer.py`: new tests asserting:
  * Spaces in control field data are spaces, not `\`.
  * Pipes are preserved verbatim.
  * Subfield delim renders as `‡`.
  * Field filter behaves the same as for the .mrk renderer.
  * Leader renders cleanly.

## Out of scope

- Changing the Ace `.mrk` editor's content format. The parser
  understands `.mrk` shape with `\` for blanks and `$` for subfield
  delim; switching the editor would require a parser rewrite. The
  edit caption already notes the format difference.
- Changing the per-record diff cards on the Tasks page. Same renderer
  underneath (`marc_diff.render_record_lines` via `field_diff`) — we
  can revisit if catalogers report similar confusion there.

## Success Criteria

1. View a record whose 008 has spaces in positions 18–20 (typical
   `260430t20252025ctuac   ob    001 0 eng d`). Display shows actual
   spaces in those positions, not `\\\` characters.
2. A 007 with fill characters shows `cr|||||||||` etc. — pipes
   preserved.
3. A 020 field display reads `   ‡a0300293054‡q(...)` — two leading
   indicator spaces, then visible `‡` subfield delimiters.
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_viewer.py
docker compose run --rm marcedit-web pytest -q
```
