Title: Rebrand as Smith Metadata Studio and design an open task migration path

Scope:
- Rebrand the product as Smith Metadata Studio, subject to Smith's formal
  name review, while preserving backward-compatible production entry points.
- Replace MarcEdit-clone positioning with an independent, open MARC21 and
  metadata workflow identity.
- Define a versioned, non-executable native task format and layered task
  authoring experience built on the existing Tasks form.
- Define a fail-closed MarcEdit task migration assistant using the supplied
  task folder as the initial compatibility corpus.
- Use Smith CORE Holdings and Items as the first end-to-end migration fixture.
- Replace cataloger-facing JSON and raw template entry with structured form
  controls and MARC previews.
- Restore useful Streamlit header activity feedback without exposing developer
  or deployment controls.
- Keep this design and all future implementation isolated from TASK-173 and
  other in-progress worktrees.

Success Criteria:
- The approved design records architecture, native task representation,
  import review states, existing-form improvements, failure handling,
  verification, licensing/rebranding, production rollout, and Streamlit
  activity-feedback requirements.
- The implementation plan explicitly references this ticket and the approved
  design.
- Every future file change for this effort is traceable to TASK-174.
- The ticket is marked Completed only after TDD verification and code review
  have no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md`

Baseline:
- `docker compose run --rm marcedit-web pytest -q` could not start because
  Docker's predefined network address pools were exhausted.
- Network-free fallback:
  `docker run --rm --network none -v <TASK-174-worktree>:/workspace:ro
  -w /workspace -e PYTHONPATH=/workspace marcedit-web:dev
  python -m pytest -q` completed with 1,573 passed and 4 explicitly reported
  skips. The skipped Compose-rendering tests require a Docker CLI inside the
  test container.
