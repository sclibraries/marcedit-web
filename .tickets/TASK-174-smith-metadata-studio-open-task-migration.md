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
- In-progress checkpoint: isolated baseline completed with 1,588 passed and
  four explicitly disclosed Docker-CLI-dependent Compose skips. The approved
  implementation plan is
  `docs/superpowers/plans/2026-07-30-task-178-native-task-schema-storage.md`.

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
