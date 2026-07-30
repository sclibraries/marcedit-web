Title: Add exact external Find and Replace migration

Parent: TASK-174

Depends on: TASK-180; TASK-184 for structural operations

Scope:
- Add explicit legacy-to-guided conversion for saved Find and Replace
  operations only when old and proposed meanings are losslessly equivalent.
- Translate external SUBFIELD_EDIT, REPLACE, and related signatures only when
  target, match, replacement, occurrence, case, and regex-dialect semantics
  are proven.
- Provide cataloger choices for empty-find instructions: add when missing,
  replace existing occurrences, or ensure exactly one occurrence.
- Keep unproven syntax such as ^b and arbitrary regular expressions over .mrk
  text recognized but unresolved until evidence establishes exact semantics.
- Preserve original review evidence and require confirmation before
  conversion.

Success Criteria:
- Every converted instruction has an exact, tested mapping to a guided
  operation and round-trips without semantic loss.
- Empty-find instructions never execute through Python empty-string
  replacement and require an explicit cataloger-selected meaning.
- Unproven regex dialects, numeric options, and flags remain visible and
  blocking.
- Existing saved operations are never silently converted.
- Sanitized synthetic fixtures provide committed guarantees; the untracked
  institutional corpus audit is local-only and loudly reported.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: Todo

Design:
- Not yet written; required before implementation.
