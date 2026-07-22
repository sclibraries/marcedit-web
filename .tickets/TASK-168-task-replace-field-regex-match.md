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

Status: Completed

Evidence:
- Transform RED: after correcting an initial test-only missing `re` import
  before any production implementation, the focused suite failed exactly on
  the four unsupported regex calls (`4 failed, 58 passed`). Transform GREEN:
  `62 passed`.
- Builder/schema/marker RED failed on the four missing behaviors: palette
  options, emitted keyword flags, legacy-marker defaults, and invalid-regex
  validation (`4 failed, 26 passed`). Builder GREEN: `30 passed`.
- Coverage proves `re.search` matching, default case sensitivity, optional
  case-insensitivity, whole-subfield replacement, invalid-pattern failure
  before record mutation, and builder validation before task persistence.
- Legacy saved markers omit the new keys unchanged while rendering explicit
  `regex=False, ignore_case=False` behavior. A mutation-tested regression also
  proves `regex=False, ignore_case=True` remains exact and case-sensitive.
- Final authoritative network-disabled Docker suite:
  `134 passed, 0 failed, 0 skipped, 0 warnings`.
- Static checks passed: `python3 -m py_compile` for `task_builder.py`,
  `transforms.py`, and `render/tasks.py`; `git diff --check` clean.
- Commits: `bdbbec5` (`feat: support regex field matching`), `3b3f3d2`
  (`feat: expose regex field match option`), and `45661f6`
  (`test: preserve exact field match case sensitivity`).
- Final independent re-review: Approved and spec compliant, with no Critical,
  Important, or Minor findings.
