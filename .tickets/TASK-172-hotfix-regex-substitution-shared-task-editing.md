Title: Correct regex subfield substitution and allow safe shared-task corrections

Scope:
- Continue from the production-compatible `legacy-hotfix-production-fixes`
  branch without importing the durable-operation deployment.
- In regex mode, replace only the text matched inside the selected subfield and
  preserve unmatched prefix/suffix text; retain exact-mode whole-value behavior.
- Define and implement an approved authorization policy for editing an existing
  shared task while preserving task identity and preventing unauthorized
  destructive or visibility changes.
- Keep production Python 3.9 and SQLite compatibility.

Success Criteria:
- A case-insensitive regex matching `TFeba` in `TFeba9780020306634` produces
  `(SCTFEBA)9780020306634`, with the requested indicators and subfield code.
- Exact matching continues to replace the complete matched subfield value.
- Invalid regexes still fail before task persistence or record mutation.
- Shared-task edit behavior follows the user-approved ownership, rename,
  delete, and visibility policy and records the acting cataloger in audit data.
- Intent-focused RED/GREEN tests, the complete Python 3.9 suite, static checks,
  scope audit, and independent review pass before the hotfix branch is pushed.

Status: In-Progress
