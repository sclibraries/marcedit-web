# TASK-060 — Deterministic note parser before AI drafting

**Status:** Completed

## Title

Add a deterministic, text-based note parser and task-authoring help surface so
common cataloging instructions can become reviewable task operations without
calling Gemini.

## Scope

- Parse a small, documented natural-language/MarcEdit-like note format in
  Python before any AI fallback.
- Convert supported lines into the same validated draft/review model used by
  TASK-059.
- Preserve unsupported or ambiguous lines as review items.
- Add a help surface that teaches users how to write notes the deterministic
  parser can understand.
- Keep Gemini as an optional fallback for unresolved lines, not the default
  path.

## Success Criteria

1. Routledge-style notes produce deterministic operations for unambiguous
   find/replace, add-field, edit-field, and subfield-code-change lines.
2. Parser output uses the existing AI draft validation/review pipeline.
3. Ambiguous lines are reported clearly and are not silently guessed.
4. The Tasks page explains the supported text patterns with examples.
5. Deterministic parsing has focused unit tests and does not require a Gemini
   API key.
6. Full test verification passes before this ticket is marked completed.
