# TASK-064 — Improve task draft prose parsing and Gemini fallback quality

**Status:** Completed

## Title

Improve deterministic task-draft prose support and reduce malformed Gemini
fallback drafts.

## Scope

- Add deterministic parsing for common cataloger prose that maps to existing
  task-builder `add-field` operations with leader condition presets.
- Improve Gemini prompt examples so `add-field.subfields` is emitted as a list
  of `[code, value]` pairs.
- Improve validation feedback for malformed `subfields` values.
- Preserve strict validation and human review; do not accept raw code or invent
  unsupported operation kinds.

## Success Criteria

1. The parser accepts `add 877 subfield m Streaming Audio when leader type is i or j`.
2. The parser accepts `add 655 indicator 2 7 subfield a Electronic scores. subfield 2 local when leader type is c or d`.
3. The parser accepts `add 655 second indicator 7 subfield a Electronic scores. subfield 2 local when leader indicates notated music`.
4. Gemini prompt includes concrete `add-field` examples with valid nested
   subfield lists.
5. Malformed `add-field.subfields` rejection explains the expected shape.
6. Existing task-draft focused tests continue to pass.
