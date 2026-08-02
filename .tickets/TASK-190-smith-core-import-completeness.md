Title: Complete deterministic migration for the supplied example-task corpus

Parent: TASK-174

Scope:
- Cover every instruction signature found in the local, untracked
  `MarcEdit Tasks/` example corpus, including the Smith CORE, EDS CC, Smith
  data-loading, and Ellis task sets. The current corpus contains 18 task
  documents, 109 unique instruction lines, and 10 instruction verbs.
- Convert the supplied tasks into open deterministic operations wherever the
  local MarcEdit package, official documentation, existing application
  behavior, or fixture equivalence tests prove the semantics.
- Add the smallest necessary structured operations or predicates for corpus
  instructions that cannot yet be represented losslessly, including the
  reviewed DELETE, ADD, REPLACE, SUBFIELD_EDIT, buildnewfield, RDAHELPER,
  COPY, EDITFIELD, SUBFIELD_REMOVE, and SORTBY families.
- Keep genuinely unproven external behavior visible and fail closed.
- Replace the diagnostic-heavy rejected-import screen with a concise
  cataloger-facing migration review that explains required choices and any
  remaining blockers.
- Never present an unknown instruction as a dead end. For every choice or
  blocker, explain the likely cataloging intent in plain language, recommend
  the closest structured operation or concrete next step, and clearly label
  the recommendation as a suggestion rather than silently guessing.
- Preserve a technical detail view for provenance and troubleshooting without
  making fingerprints and raw diagnostics the primary cataloger experience.
- Keep real institutional task files local and untracked. Commit only
  sanitized synthetic fixtures and a generated compatibility manifest that
  records instruction signatures without exposing institutional record data.

Success Criteria:
- Every unique instruction in the supplied example corpus receives a
  non-vacuous, tested classification: automatic conversion, an explicit
  cataloger choice, or a documented blocking reason when exact semantics
  remain demonstrably unproven.
- All fully proven example tasks import into editable deterministic drafts in
  source order without opaque Python or executable external syntax.
- DELETE, supported ADD conditions, proven Build Field templates, and reviewed
  RDA behavior use structured operations rather than opaque Python.
- Proven COPY, EDITFIELD, SUBFIELD_REMOVE, structural REPLACE, special
  SUBFIELD_EDIT, and Build Field flag combinations round-trip through the task
  editor without loss.
- External instructions are never guessed, silently discarded, or executed as
  raw external syntax.
- Catalogers see a bounded actionable summary first and may expand technical
  provenance when needed.
- Fully converted imports open as editable drafts with a concise conversion
  summary; technical source lines and fingerprints are collapsed by default.
- Every non-converted instruction has an actionable cataloger-facing card with
  a plain-language explanation, a recommended structured recreation path, and
  a direct editor action when the recommendation can be prefilled safely.
- Partially converted tasks open as editable drafts with converted operations
  and blocking suggestion cards retained in source order. Drafts may be saved,
  but preview and execution remain blocked until every card is resolved.
- A checked-in compatibility manifest is reproducibly generated from
  sanitized fixtures, while an explicit local-only corpus test reports whether
  all currently supplied examples remain covered.
- Intent-focused RED/GREEN tests, complete Docker verification, and review
  pass before completion.

Status: Todo

Design: [Example-task import completeness design](../docs/superpowers/specs/2026-08-02-task-190-example-task-import-completeness-design.md)

Plan: [Example-task import completeness implementation plan](../docs/superpowers/plans/2026-08-02-task-190-example-task-import-completeness.md)
