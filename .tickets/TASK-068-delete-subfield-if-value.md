# TASK-068 — Delete subfield by matched value

**Status:** Completed

## Title

Add a flexible typed operation for deleting subfields only when their value
matches a cataloger-specified condition.

## Scope

- Add a low-level transform that removes subfields by tag, code, value, and
  match mode.
- Add a task-builder operation for exact, contains, and regex matching.
- Let validated draft generation use the operation through the normal palette.
- Teach deterministic note parsing to convert MarcEdit-style `Edit subfield`
  blocks such as `300 b :` into the typed operation.
- Keep malformed or ambiguous subfield-edit notes in review.

## Success Criteria

1. `Edit subfield (remove :-only fields) 300 b :` parses into
   `delete-subfield-if-value` with exact matching and trim enabled.
2. The transform removes only matching subfields and preserves other subfields.
3. The task-builder operation renders and round-trips through `# OP:` markers.
4. The AI draft validator accepts valid params and rejects malformed params.
5. Focused tests and the Docker test suite pass before completion.
