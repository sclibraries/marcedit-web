Title: Refuse to run saved tasks that contain untranslated MarcEdit placeholders

Status: In-Review
Size: S
Tier: normal — changes which saved tasks can run
Milestone: M0
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-265

Why:
- The old MarcEdit importer saved lines it couldn't translate as `custom`
  operations whose code is only a `# TODO …` comment. They do nothing, so a
  run finishes as if it did everything. In production, 5 of the 8 saved tasks
  contain 44 of these (2026-11-23). Catalogers must not get silently
  incomplete records.

Scope:
- `task_preflight.assert_runnable_operations` also rejects a `custom`
  operation whose `code` has a `# TODO` comment line and no executable line
  (every non-blank line is a comment or `pass`). Every run and preview path
  already goes through it.
- The error says how many MarcEdit instructions were never translated and
  lists the first five placeholder texts (without `# TODO:`), then how many
  more there are.

Out of scope:
- Rebuilding or editing the saved tasks, the importers, saving or opening
  tasks, database changes.
- Custom operations with executable code, and comment-only ones without
  `# TODO`.

Likely files:
- `marcedit_web/lib/task_preflight.py`
- `tests/test_task_authoring.py`

Acceptance tests:
- A body holding a `custom` placeholder is refused before execution, and the
  message has the count, the first five texts and "N more": the cataloger
  must see what the task would have skipped.
- Still runnable: a `custom` operation with a `# TODO` comment plus
  executable code; a comment-only `custom` without `# TODO`; a `# TODO`
  comment with no operation marker (existing test). Real work must not be
  blocked.
- A task with a placeholder can still be saved and opened, so it can be
  repaired (existing tests in `tests/test_tasks_workspace_modes.py`).
- Existing migration-blocker refusals keep their messages.

Test change allowed:
- `test_submission_preflight_composes_add_build_and_empty_find_issues`
  expects a placeholder not to block. Change only that expectation: both the
  placeholder and the empty Find are reported.

Verification:
- Full suite in `marcedit-web:dev` and the host deploy-file tests (AGENTS.md
  "Verification commands").

Handoff:
- (orchestrator fills in after the check)

Review:
- (orchestrator fills in)
