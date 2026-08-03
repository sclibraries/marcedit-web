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

Status: In-Progress (2026-08-03 remediation)

Prior implementation evidence:
- Added deterministic import provenance binding by attaching per-operation digests and
  enforcing them on retained-draft restore.
- Added bounded task-name derivation for imported filenames with deterministic
  hash-based suffixing when source filenames exceed size limits.
- Added negative and tamper tests in:
  - `tests/test_external_task_migration.py` (existing cases unchanged)
  - `tests/test_marcedit_import.py` (`test_long_filename_derivation_bounds_and_stability`)
  - `tests/test_tasks_workspace_modes.py` (`operation_digest` and `operations` bound/corruption checks)
- Focus tests pass for this work:
  - `pytest tests/test_external_task_migration.py` (143 passed)
  - `pytest tests/test_marcedit_import.py` (33 passed)
  - `pytest tests/test_tasks_workspace_modes.py -q -k "not raw_regex"` (242 passed, one expected legacy preexec issue outside this change)

Remediation scope:
- Make the committed suite parse and run under the required Python 3.9
  container runtime.
- Make migration blockers actionable in the task editor, including safe
  suggested-operation replacement and retained import summaries/provenance.
- Preserve unselected drafts from multi-entry archives.
- Add the planned local corpus audit and make its fixture test cover every
  instruction family rather than only ADD and Build Field.
- Regenerate the cataloger operation reference, remove fixture whitespace
  drift, and rerun the complete Docker and browser verification gates.

Remediation verification checkpoint (2026-08-03):
- Focused TASK-190 suite in the rebuilt runtime image: `393 passed`.
- Full source-mounted suite with the local corpus mounted read-only:
  `2423 passed, 4 skipped`; the skips are Docker CLI checks unavailable inside
  the container.
- Local corpus audit: `18 documents`, `297 instructions`, `293 converted`,
  `4 actionable blockers`, `0 unclassified`, and `0 items without a next
  action`.
- Code-generation/native guards: `79 passed`; both checked-in manifests are
  unchanged. `git diff --check` is clean.
- Full runtime-image suite: `2379 passed, 40 skipped, 9 failed`. The nine
  failures are the pre-existing image-only product-identity tests that read
  repository files intentionally omitted from the runtime image; no
  TASK-190 test failed. The runtime image includes the corpus audit script.
- Rebuilt local Streamlit service is healthy and returns HTTP 200 at
  `http://localhost:8501/`. Playwright reaches the Five-College Google
  sign-in page, but no Google account session is available in this review
  environment. Authenticated browser verification remains pending; do not
  treat the HTTP smoke check or the sign-in-page reachability as a substitute.

Post-checkpoint importer regression (2026-08-03):
- A real SC FOLIO archive import exposed a retained-draft fingerprint mismatch:
  Add Field defaults were normalized before validation but fingerprinted before
  normalization when the draft was created. Both Smith CORE entries were
  incorrectly downgraded to invalid after the first Streamlit rerun.
- Retained-draft validation now checks provenance against the exact stored
  operation payload and normalizes only after that integrity check. Existing
  digest, provenance-order, identity, and blocker-tamper checks remain intact.
- The exact local `SC FOLIO core tasks.task` archive now retains both Smith CORE
  Instance and Holdings/Items entries as `draft_ready` editable drafts.
- Regression/importer/migration suites: `247 passed`. Full source-mounted suite
  with the local corpus: `2425 passed, 4 skipped`; the four skips remain the
  Docker CLI checks unavailable inside the container.
- Imported editor widgets now use their keyed session-state values without also
  supplying conflicting defaults, removing Streamlit's duplicate-value warning.
  The optional shortcut is labeled **Add full Smith RDA cleanup profile (6
  operations)** and explicitly states that it is not part of the imported
  source task. Editor/RDA/importer/migration suites: `262 passed`.

Design: [Example-task import completeness design](../docs/superpowers/specs/2026-08-02-task-190-example-task-import-completeness-design.md)

Plan: [Example-task import completeness implementation plan](../docs/superpowers/plans/2026-08-02-task-190-example-task-import-completeness.md)
