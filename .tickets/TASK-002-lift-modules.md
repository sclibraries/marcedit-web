# TASK-002 — Lift generic modules + Python 3.9 backport

**Status:** Completed (Stage 2)
**Stage:** 2 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Lift the generic modules from `marc-processing` and `marc-diff` (extracted
into `/tmp/marcedit-inspect/` during planning) into `marcedit_web/lib/`,
with surgical de-Smithification per the plan's reuse table. Verify pytest
green inside the Docker image.

## Scope (per the plan's Reuse Map)

Source → target, with the changes from `the-goal-of-this-sequential-sifakis.md`:

- `marc-processing/scripts/marc_processing/errors.py` → `marcedit_web/lib/errors.py`
- `.../preflight.py` → `lib/preflight.py` (strip Smith bits)
- `.../transforms.py` → `lib/transforms.py` (strip libproxy/container/OCLC)
- `.../tasks.py` → `lib/tasks.py` (drop shipped-task auto-load)
- `.../task_builder.py` → `lib/task_builder.py` (drop Smith palette entries)
- `.../editor.py` → `lib/editor.py` (drop workflow round-trip)
- `.../marcedit_import.py` → `lib/marcedit_import.py` (as-is)
- `.../viewer.py` → `lib/viewer.py` (drop CLI TTY + diff())
- `.../reporting.py` → `lib/reporting.py` (drop Smith warnings)
- `.../report.py` → `lib/report.py` (strip Smith fields; optional)
- `marc-diff/marc_diff.py` → `lib/marc_diff.py` (as-is)
- `marc-processing/marc-rules.txt` → `data/marc-rules.txt` (as-is for now;
  extension format is Stage 4)

Tests: lift the corresponding tests from `marc-processing/tests/` into
`tests/`. Drop Smith-coupled test files (profiles, registry, workflows,
inbox, gui, gui_runner, workflow_ordering, phase3_*, atomic_writes,
overwrite, migration, report — except the bits that test the generic
helpers).

## Success Criteria

1. Every file in the Reuse Map exists at its target path.
2. No file references the dropped modules (workflows, registry, inbox,
   profiles, rda, gui, gui_runner, cli) — `grep -rE 'from (\\.)?(workflows|registry|inbox|profiles|rda|cli|gui|gui_runner)' marcedit_web/lib/` empty.
3. `docker compose run --rm marcedit-web pytest -q` returns 0 with no
   skipped tests due to import errors.
4. `docker compose up -d` still produces a working `/_stcore/health` ok.
5. No runtime `X | Y` unions, no `match`/`case`, no `tomllib`, no
   `slots=True` in any lifted file (Python 3.9 compatibility).

## Verification result (2026-05-21)

- Lifted modules (with surgical strips per the Reuse Map):
  `errors.py`, `transforms.py`, `viewer.py`, `tasks.py`, `editor.py`,
  `task_builder.py`, `marcedit_import.py`, `preflight.py`,
  `reporting.py`, plus `marc_diff.py` lifted as-is.
- Dropped `report.py` (tightly coupled to engine concepts we removed
  from `RunSummary`; deferred per the plan's v1.5 list).
- `data/marc-rules.txt` lifted as-is (the `:help`/`:byte` format
  extensions land in Stage 4).
- Static scan clean: zero `marc_processing` import references remain
  in `marcedit_web/`; zero references to dropped modules (workflows,
  registry, inbox, profiles, rda, cli, gui, gui_runner); zero runtime
  `X | Y` unions, match-statements, `tomllib`, or `slots=True`.
- Focused smoke + lib-surface tests added under `tests/`:
  `test_smoke_imports.py`, `test_errors.py`, `test_transforms.py`,
  `test_preflight.py`, `test_viewer.py`, `test_reporting.py`,
  `test_tasks.py`, `test_editor.py`, `test_task_builder.py`,
  `test_marcedit_import.py`. Wider port of the original marc-processing
  test corpus deferred to a follow-up ticket.
- `docker compose run --rm marcedit-web pytest -q` → **84 passed in
  0.14s** under Python 3.9-slim.
- `docker compose up -d` + `/_stcore/health` → still `ok`; teardown
  clean.

Success criteria 1-5 satisfied.
