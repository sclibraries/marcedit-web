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

Verification Evidence:
- Regex RED reproduced the whole-value loss and related semantics gaps:
  `5 failed, 61 passed`. Palette help had a separate expected RED failure.
  GREEN passed `98` transform/builder tests. The production case now maps
  `TFeba9780020306634` to `(SCTFEBA)9780020306634`; prefix/suffix text,
  repeated matches, capture references, exact compatibility, and invalid
  pattern/replacement non-mutation are covered.
- Shared storage RED failed all seven new behaviors against the missing API:
  `7 failed, 19 passed`. GREEN passed `26` real-SQLite tests covering identity
  preservation, private/unshared/deleted rejection, and same-second stale
  conflict detection.
- Shared UI RED reproduced the owner-only path and missing collaborator state:
  `12 failed, 5 passed`. GREEN passed `17` focused tests and `147` task/editor
  regressions covering the authorization matrix, tampered state, owner
  compatibility, stable widget keys, inline conflict handling, and audit data.
- Final combined TASK-171/TASK-172 regression gate passed under Python 3.9:
  `352 passed in 7.61s`, with no skips or warning summary.
- Complete Python 3.9 suite passed: `1310 passed in 21.69s`, with no skips or
  warning summary. `compileall`, fixed-base `git diff --check`, clean status,
  prohibited-scope audit, merge audit, and exact-base check passed.
- Independent whole-range review found no Critical or Important issues and
  returned **Ready: Yes**. Two non-blocking follow-ups were recorded: directly
  parameterize missing/unshared callback errors, and explicitly reset/test
  collaborative context in the inherited Clear-my-tasks lifecycle path.

Implementation Commits:
- `6cc86d4` — regex matched-span substitution and form guidance.
- `0bfdcff`, `4105d33` — atomic shared-task correction storage and accurate
  access documentation.
- `056e261` — shared-task editor authorization, protected save flow, and audit
  attribution.

Status: Completed
