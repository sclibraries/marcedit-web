Title: Rebrand as Smith Metadata Studio and design an open task migration path

Scope:
- Prepare Smith Metadata Studio as the working public name, subject to Smith's
  formal name review, while centralizing the name and preserving every current
  production entry point.
- Replace MarcEdit-clone positioning with an independent, open MARC21 and
  metadata workflow identity.
- Define a versioned, non-executable native task format and layered task
  authoring experience built on the existing Tasks form.
- Define compiler-fingerprinted execution snapshots so trusted compiler changes
  regenerate native tasks without masking same-fingerprint corruption.
- Define a fail-closed MarcEdit task migration assistant using the supplied
  task folder as the initial compatibility corpus.
- Use Smith CORE Holdings and Items as the first end-to-end migration fixture.
- Replace cataloger-facing JSON and raw template entry with structured form
  controls and MARC previews.
- Keep this design and all future implementation isolated from TASK-173 and
  other in-progress worktrees.
- Leave Streamlit activity-header restoration to TASK-175 and the consolidated
  ITS installation/routing envelope to TASK-173.

Success Criteria:
- The approved design records architecture, native task representation,
  import review states, existing-form improvements, failure handling,
  compiler migration, local-corpus skip behavior, verification,
  licensing/rebranding, and production-compatibility requirements.
- The implementation plan explicitly references this ticket and the approved
  design.
- Every future file change for this effort is traceable to TASK-174.
- The ticket is marked Completed only after TDD verification and code review
  have no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md`

Phase 1:
- TASK-176: neutral product identity and licensing baseline.
- Plan:
  `docs/superpowers/plans/2026-07-29-task-174-phase-1-product-identity-licensing.md`
- Completed checkpoint: TASK-176 evidence records the reviewed
  `b1234eb..b53f9c5` range, 58 focused passes, 1,585 complete-suite passes,
  four disclosed skips, corrected browser identity, Docker licensing
  artifacts including pytest, reusable dependency-install layering,
  preserved technical entry points, and no unresolved Critical or Important
  findings. Browser acceptance has a durable accessibility snapshot; the
  unavailable screenshot is an explicit Minor plan deviation. See the tracked
  `.tickets/TASK-176-neutral-product-identity-licensing.md` and
  `docs/superpowers/evidence/task-176-record-editor-browser-smoke.md`.
  The local-only `.superpowers/sdd/task-176-task-4-report.md` is ignored by Git
  and absent from clean checkouts.
- Completed checkpoint: TASK-177 finalizes the display-only public name as
  `Smith Metadata Studio` in implementation commit `2481c39`. TDD recorded the
  intended two-test RED, then 2 narrow and 58 focused passes with zero skips.
  The rebuilt `marcedit-web:task-177` image reused its dependency-install layer,
  passed packaged license/notice checks, and produced 1,586 complete-suite
  passes with four disclosed Docker-CLI-dependent Compose skips. Trusted
  public-mode browser acceptance verified the exact title and two headings,
  upload controls, and absence of the superseded and prohibited public labels;
  both the accessibility snapshot and successful single-attempt screenshot are
  tracked under `docs/superpowers/evidence/`. The initial private-mode sign-in
  gate required only a disposable `MARCEDIT_WEB_MODE=public` harness correction;
  source and production defaults were unchanged. Technical `marcedit-web`,
  `MARCEDIT_WEB_*`, `/marcedit-web/`, and `MarcEditor` route/script identifiers
  remain preserved. Independent review approved exact range
  `5b7824e..b7a1c07592c69ef2560256ec6de57577d6a973f6`: spec compliance and
  code quality passed with zero Critical, Important, or Minor findings.
  TASK-177 is `Completed`; TASK-174 remains `In-Progress`.

Phase 2:
- TASK-178: native task schema and storage compatibility.
- Completed checkpoint: TASK-178 documents schema version `1` and the
  `delete_tag`, structured `build_field`, and `sort_fields` compiler boundary;
  preserves legacy rows through schema version 14; and verifies atomic native
  saves, compiler-fingerprinted execution snapshots, fail-closed integrity and
  revision races, stale migration, and audit evidence. The exact
  `marcedit-web:task-178` candidate packaged its dependency, license, schema,
  and compiler manifest, then passed 102 focused tests with zero skips and
  1,635 complete-suite tests with four explicitly disclosed
  Docker-CLI-dependent Compose-rendering skips. Scope audit found no
  infrastructure, cataloger UI, authorization, technical identifier, or local
  corpus changes. Independent review approved exact range
  `e112aa3..5441330c063eebf4988bad95339fe120ea731e2a` with zero Critical,
  Important, or Minor findings. TASK-178 is `Completed`; TASK-174 remains
  `In-Progress` for its remaining form, migration, corpus, and preview phases.

Phase 3:
- TASK-179: structured Add Field and Build Field authoring in the existing
  Tasks form, with transparent MARC syntax, deterministic previews, and
  sanitized Smith CORE acceptance examples.
- Completed checkpoint: TASK-179 replaces normal Add Field JSON and Build Field
  raw templates with ordered rows and typed segments, provides deterministic
  explanations and first-record previews, preserves exact save/reopen state,
  and fails closed on ambiguous imports or unknown stored shapes. The final
  candidate passed 227 focused tests with zero skips; its full read-only-mounted
  Docker run recorded 1,691 passes, zero failures, and 29 disclosed
  environment/build-context skips. The native compiler manifest remained
  unchanged. Independent review approved `293ecb6..2e887ee` with zero
  Critical, Important, or Minor findings, and cataloger browser acceptance
  completed on synthetic data. TASK-179 is `Completed`; TASK-174 remains
  `In-Progress`.
- TASK-180: structured Find/Replace and Subfield Edit authoring is
  implemented through an evidence checkpoint but remains `In-Progress`.
  Focused and native-contract guards pass, and a supplementary
  TASK-179-precedent read-only-mounted complete suite passes with five
  disclosed environment/corpus skips. The required rebuilt-image complete
  suite still has eight known repository-file-availability failures, and all
  ten browser checks remain unavailable because the required in-app
  browser-control runtime was not exposed. All nine Important findings were
  resolved by `9c6dca1`, `cc7cf4d`, `5af4fad`, `3051485`, `d7e9a20`, and
  `d94cd86`, plus stale-preview correction `5ea7e1b`, with clean scoped
  re-reviews; `d94cd86` also makes condition-skipped preview an explicit
  successful outcome. TASK-180 is not a completed checkpoint; TASK-184 and
  TASK-185 remain deferred.
- TASK-181: deferred explicit deterministic RDA operations.
- TASK-182: deferred explicit MARC field reordering as both a quick action and
  an optional task step, while View continues to preserve source order under
  TASK-169.
- TASK-183: deferred cataloger-facing reference and contextual help for every
  deterministic Tasks operation.

Related Tickets:
- TASK-175 owns Streamlit activity-header restoration.
- TASK-173 owns the single-touch ITS installation and routing envelope.

Baseline:
- `docker compose run --rm marcedit-web pytest -q` could not start because
  Docker's predefined network address pools were exhausted.
- Network-free fallback:
  `docker run --rm --network none -v <TASK-174-worktree>:/workspace:ro
  -w /workspace -e PYTHONPATH=/workspace marcedit-web:dev
  python -m pytest -q` completed with 1,573 passed and 4 explicitly reported
  skips. The skipped Compose-rendering tests require a Docker CLI inside the
  test container.
