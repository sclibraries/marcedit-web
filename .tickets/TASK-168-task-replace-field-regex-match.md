Title: Add regex matching to replace-field-subfield-and-indicators tasks

Scope:
- Reproduce the current exact-only match behavior for
  `replace-field-subfield-and-indicators`.
- Add explicit regex and case-insensitive options for matching the selected
  source subfield while preserving the existing exact, case-sensitive default
  and saved-task compatibility.
- Use `re.search` semantics and define failure behavior for invalid regular
  expressions.

Success Criteria:
- Existing exact-match tasks behave unchanged.
- Regex-enabled tasks can match the requested `035$a` pattern such as `TFeba`
  within a complete subfield value.
- Regex matching is case-sensitive by default and optionally case-insensitive.
- Invalid patterns fail clearly before persistence or record mutation.
- Intent-focused tests, applicable suites, and review pass without unresolved
  Critical or Important findings.

Status: In-Progress
