# TASK-091 — Structured cataloger-friendly record editing

**Status:** Completed
**Priority:** Tier 3 — cataloger usability / edit safety
**Source:** Cataloger feedback: raw `.mrk` fixed fields are difficult to edit

## Title

Improve record editing so catalogers do not have to edit raw MarcEdit `.mrk`
fixed-field text for common record changes.

## Problem

The current single-record editor exposes MarcEdit-style `.mrk` text such as:

```text
=LDR  09568cam a2200841Mi 4500
=001  in00005482679
=005  20250131195348.7
=006  m\\\\\o\\d\\\\\\\\
=007  cr\cn|||||||||
=008  180306s2018\\\\enka\\\\o\\\\\000\0\eng\d
```

That format is round-trip friendly for the application, but it is difficult for
catalogers to edit safely. Fixed fields especially require knowing byte
positions, placeholder characters, escaping conventions, and MARC-specific
meaning.

## Scope

- Add a structured editing path for a single record that presents common fields
  in cataloger-friendly controls rather than only raw `.mrk` text.
- Prioritize fixed fields that are hard to edit in raw text:
  - Leader (`LDR`)
  - `006`
  - `007`
  - `008`
- Preserve the existing raw `.mrk` editor as an advanced / fallback editor.
- Keep edits scoped to one selected record at a time, matching the current
  per-record edit safety model.
- Re-parse and validate after save so invalid records are not silently written
  back into the loaded batch.

## Success Criteria

1. A cataloger can edit common fixed-field values without manually counting
   byte positions in raw `.mrk`.
2. The UI labels fixed-field positions with their MARC meaning where rules data
   already provides that information.
3. Saving a structured edit updates the underlying `pymarc.Record` and refreshes
   the loaded batch.
4. Invalid structured edits are rejected with clear inline feedback.
5. The raw `.mrk` editor remains available for fields or edits not yet covered
   by the structured editor.
6. Tests cover at least one successful structured fixed-field edit and one
   invalid edit that blocks save.

## Notes

- TASK-031 already added an `008` helper. This ticket should evaluate whether
  to extend that pattern or replace it with a more unified structured editor.
- The design should avoid overbuilding a full MARC cataloging client. The first
  pass should focus on high-risk / high-friction fixed-field edits surfaced by
  cataloging feedback.

## Implementation Plan

Ticket link: `.tickets/TASK-091-structured-record-editing.md`

1. Add focused tests for a structured fixed-field model covering `LDR`, `006`,
   and `007`.
2. Create a pure helper module that exposes labeled positions and applies byte
   edits without requiring catalogers to count positions manually.
3. Extend the existing `fixed_field_helper` Streamlit renderer with a compact
   `LDR / 006 / 007` helper, keeping the existing raw `.mrk` editor and 008
   helper unchanged.
4. Mount the helper in View and Workspace Edit wherever single-record editing
   is available.
5. Run focused tests and commit TASK-091 as a rollback checkpoint.
