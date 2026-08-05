Title: Convert repeated partner-task patterns into deterministic pymarc operations

Parent: TASK-174

Design: [Partner-corpus pattern migration](../docs/superpowers/specs/2026-08-03-task-192-partner-pattern-pymarc-operations-design.md)

Scope:
- Recognize reviewed multi-instruction patterns in the TASK-191 partner corpus
  and convert them into concise native operations.
- Add deterministic pymarc-backed operations for per-source-field creation,
  institution mappings, explicit field copying, generalized predicates, and
  explicit subfield actions.
- Preserve source ranges and actionable blockers when semantics are unproven.
- Keep arbitrary Python and opaque external option numbers out of stored native
  task definitions.
- Preserve the existing `copy-field` operation contract and keep all new
  structured operation kinds outside both AI-draft schemas.

Success Criteria:
- Reviewed repeated 856 and 945-949 primitives with proven source evidence
  convert to concise editable operations with equivalent golden-record output;
  contiguous workflows whose TASK_LIST looping dependency is absent remain
  explicit actionable blockers rather than accepted adapters.
- Every newly accepted external signature has before/after evidence and a
  characterization test; repetition alone is never treated as proof.
- Preview reports matched, created, replaced, and skipped counts and enforces a
  per-record expansion bound.
- Missing TASK_LIST dependencies remain actionable and are never guessed.
- Existing AI drafting behavior and every previously saved `copy-field` task
  remain unchanged, with characterization coverage.
- The complete partner corpus has a checked-in converted/blocker report with
  zero silent omissions and zero blockers without a next action.
- Supported Python 3.9 Docker tests and independent review pass with no
  unreported skips or unresolved Critical/Important findings.

Implementation checkpoint:
- Partner operations now report preview counts and enforce per-record limits.
- Task-wide expansion totals are aggregated across sandbox chunks before a
  candidate chunk is appended.
- Unfiltered COPY and TASK_LIST blockers now prefill the closest controlled
  operation or dependency identity and state the cataloger’s next action.
- Every unresolved migration blocker now retains that next action in the
  editable draft and displays it on the task card, dialog, and import review.
- The partner corpus report is checked in at
  `docs/partner-task-corpus-report.md` and has a freshness test.
- Focused Python tests pass. The Python 3.9 hotfix Compose suite passes with
  2,515 tests passed and 18 explicit environment/corpus skips; no failures
  were hidden by the review topology.

Status: In-Progress
