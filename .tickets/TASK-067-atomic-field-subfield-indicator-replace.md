# TASK-067 — Atomic field/subfield/indicator replacement

**Status:** Completed

## Title

Add a typed operation for MarcEdit-style field find/replace that updates
indicators and subfield value on the same matched field.

## Scope

- Add a task-builder operation for matching a variable field by tag,
  indicators, subfield code, and exact subfield value.
- Render the operation through a low-level transform that mutates only matching
  fields.
- Teach deterministic note parsing to convert the Routledge `035` MarcEdit
  find/replace block into the new typed operation.
- Let Gemini use the operation through the existing allowed-operation palette.
- Keep ambiguous variants unsupported.

## Success Criteria

1. `=035  \\$aTFeba` → `=035  9\$a(SCTFEBA)` parses into a supported typed operation.
2. The transform mutates only matching `035` fields.
3. The task-builder operation renders and round-trips through `# OP:` markers.
4. The AI draft validator accepts the operation with valid params and rejects
   malformed params.
5. Full focused tests and Docker tests pass before completion.
