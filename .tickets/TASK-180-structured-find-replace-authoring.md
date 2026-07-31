Title: Add structured deterministic Find and Replace task authoring

Parent: TASK-174

Scope:
- Extend the existing Tasks form with one guided Find and Replace operation
  after completed TASK-179 establishes the shared authoring patterns.
- Cover one control-field value, one subfield code, or all subfield values in
  one tag.
- Cover contains, starts-with, ends-with, whole-value, and optional raw-regex
  matching; matched-text, whole-selected-value, prepend, and append behavior;
  first/all occurrences; and case handling.
- Block empty-find SUBFIELD_EDIT imports and submission of existing generated
  empty-find operations because Python empty-string replacement silently
  inserts text between every character.
- Keep the unproven external `^b` signature visible and unresolved rather than
  importing it as a literal replacement or guessing that it means prepend.
- Preserve existing saved operation semantics and defer external conversion,
  structural field/tag/indicator changes, tag ranges, and structured patterns
  to TASK-184 and TASK-185.
- Keep the work deterministic and reviewable; do not add AI task generation.

Success Criteria:
- Catalogers can express the Smith 035 TFeba replacement through labeled
  controls and preview the identifier-preserving result before execution.
- Replacement scope and preservation behavior are explicit and covered by
  intent-focused tests.
- Advanced raw regex remains available, round-trips exactly, and requires a
  current successful sandbox preview.
- Save/reopen is lossless and existing saved operation kinds retain their
  established behavior.
- Quick Find/Replace and AI drafting behavior remain unchanged, verified by
  characterization tests.
- Empty-find imports and already-saved generated empty-find form operations
  fail loud instead of executing.
- Unproven `^b` instructions remain visible, unresolved, and unexecuted.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-30-task-180-structured-find-replace-authoring-design.md`

Plan:
- `docs/superpowers/plans/2026-07-30-task-180-core-structured-find-replace-authoring.md`

Verification Checkpoint:
- Candidate implementation commit: `5ea7e1b`.
- Docker image:
  `sha256:4f867a65b63805f682a374c55c512d8d4bfd48c84858d922a56dfe0780916e97`.
- Focused Docker: 475 passed, 0 failed, 0 skipped, and 0 warnings in
  14.06 seconds. This set includes
  `tests/test_guided_replace_validation.py` and `tests/test_tasks_export.py`.
- Native contract:
  `test_checked_in_contract_matches_every_golden_definition` passed 1/1 in
  0.11 seconds, and
  `marcedit_web/schemas/native-task-compiler-contract-v1.json` has no diff
  from `main`.
- Required complete rebuilt-image Docker run: 1,823 passed, 8 failed,
  39 skipped, and 0 warnings in 47.13 seconds. All eight failures are
  pre-existing `tests/test_product_identity.py` checks whose repository-only
  `README.md`, `Dockerfile`, TASK-176 ticket, and phase-one plan are absent
  from `/app` in the default image/Compose mounts. The 39 reported skips are:
  24 deployment/configuration checks for files intentionally absent from the
  image (2 private-service, 4 deployment-doc, 1 public-service, 1 worker,
  1 deploy script, 1 install script, 10 preflight script, 1 environment
  example, 1 ITS setup, 1 watchdog service, and 1 watchdog timer);
  13 Compose checks (3 pull-file, 4 Docker-CLI-required, 3 `.dockerignore`,
  and 3 `Dockerfile`); 1 syntax-reference check because the reference is
  absent from the image; and 1 unavailable institutional-corpus check.
- Supplementary TASK-179-precedent read-only mounted Docker run:
  1,865 passed, 0 failed, 5 skipped, and 0 warnings in 47.00 seconds.
  The five skips are four Compose-rendering checks requiring a Docker CLI
  inside the container and one unavailable institutional-corpus check;
  synthetic fixtures remain authoritative.
- Browser acceptance:
  `docs/superpowers/evidence/task-180-guided-find-replace-browser-smoke.md`.
  The initial isolated service harness was healthy, but all ten UI checks,
  the accessibility snapshot, and the screenshot remain unavailable because
  controller discovery reconfirmed that the required `node_repl js`
  browser-control runtime is not exposed. External Playwright was not
  substituted.
- Independent review: the review rounds found 0 Critical and 9 Important
  findings in total. Commit `9c6dca1` resolved hidden target-switch state plus
  discard-count and technical-transparency gaps; `cc7cf4d` completed
  compatibility-matrix and repeated-value occurrence coverage; `5af4fad`
  moved raw pattern/replacement validation into the bounded sandbox; and
  `3051485` resolved the two remaining UI-state findings for hidden controls
  and Streamlit-safe mode transitions. Commit `d7e9a20` applies mode
  confirmations immediately before the rerun, and `d94cd86` makes preview
  setup/launcher failures fail closed. `d94cd86` also resolves the
  condition-skip design question by representing it as an explicit successful
  preview outcome. Commit `5ea7e1b` hides stale preview evidence when the
  current request no longer matches it. Scoped re-reviews were clean, with no
  remaining Critical or Important findings. Final whole-branch review of
  `f9b8968..0c1c14a` found zero Critical, Important, or Minor findings and
  assessed the code as ready for cataloger browser testing.
- Completion is blocked until the required rebuilt-image suite has zero
  failures (or its eight known repository-file failures receive an explicit
  acceptance decision) and all ten browser checks are completed with concrete
  evidence. This checkpoint does not mark TASK-180 completed.
