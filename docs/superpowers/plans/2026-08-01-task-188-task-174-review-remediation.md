# TASK-188 TASK-174 Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the confirmed TASK-174 correctness, safety, verification, and ticket-state defects without expanding external-task compatibility.

**Architecture:** Keep structural matching in `structural_replace.py`, RDA policy in `rda_operations.py`, adapter dispatch in `external_task_migration.py`, and source rendering in `codegen_safety.py`/`task_builder.py`. All behavior changes are fail-closed and begin with a focused regression test.

**Tech Stack:** Python 3.9, pymarc, pytest, Streamlit, Docker.

## Global Constraints

- Ticket: [TASK-188](../../../.tickets/TASK-188-task-174-review-remediation.md).
- Work only in the isolated `task-186` branch/worktree.
- Do not change production routes, authentication, services, workers, or ITS-managed configuration.
- Preserve source field order for retagging; canonical reordering remains an explicit TASK-182 operation.
- Do not infer undocumented external syntax.

---

### Task 1: Ticket and image-only evidence

**Files:**
- Modify: `.tickets/TASK-180-structured-find-replace-authoring.md`
- Modify: `.tickets/TASK-187-persist-import-diagnostics.md`
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`
- Modify: `tests/test_operation_reference_registry.py`

- [x] Remove TASK-187's stale pre-completion blocker paragraph and distinguish the eight image-only failures from the loud operation-reference skip.
- [x] Add the same loud missing-reference skip used by `test_task_authoring_corpus.py` to the generated operation-reference freshness test.
- [x] Run the image-only and mounted focused tests and record exact outcomes.

### Task 2: Structural empty-find and raw-regex safety

**Files:**
- Modify: `tests/test_structural_replace.py`
- Modify: `marcedit_web/lib/structural_replace.py`
- Modify: `marcedit_web/lib/task_builder.py`
- Modify: `marcedit_web/render/task_operation_dialog.py`

- [x] Add RED tests proving `replace_matched_text` rejects an empty Find, structured patterns reject an empty piece list, and retag/set-indicators require explicit `match_mode="all"` when no Find is supplied.
- [x] Add RED tests proving invalid raw-regex capture references fail validation before record execution.
- [x] Implement `match_mode="all"`, hide Find for that mode, and reject every implicit empty pattern.
- [x] Remove the unreachable `data_field` matched-text branch and document retag's deliberate source-position preservation.
- [x] Run `tests/test_structural_replace.py` and task-authoring/dialog tests.

### Task 3: RDA correctness

**Files:**
- Modify: `tests/test_rda_operations.py`
- Modify: `marcedit_web/lib/rda_operations.py`
- Modify: `marcedit_web/lib/task_builder.py`
- Modify: `marcedit_web/lib/operation_reference.py`
- Regenerate: `docs/operation-reference.md`

- [x] Add RED tests for print text, online text (`007=cr`), ambiguous unsupported carriers, 264 second indicator `1`, boundary-safe abbreviation expansion, relator preservation/deduplication, and unknown existing-field policy rejection before mutation.
- [x] Replace material-only mappings with evidence-specific content/media/carrier mappings.
- [x] Preserve `$4`, add missing `$e` once, set 264 indicator 2 to `1`, and use regex token boundaries for reviewed abbreviations.
- [x] Update fixed profile labels and documentation, regenerate the reference, and run RDA/reference tests.

### Task 4: External adapter precision

**Files:**
- Modify: `tests/test_external_task_migration.py`
- Modify: `tests/test_marcedit_import.py`
- Modify: `marcedit_web/lib/external_task_migration.py`
- Modify: `marcedit_web/lib/marcedit_import.py`
- Modify: `.tickets/TASK-185-external-find-replace-migration.md`

- [x] Add RED tests proving every caret-prefixed Find remains unresolved and adapter dispatch uses `ADAPTER_REGISTRY`.
- [x] Route `adapt_instruction` through registry entries and register supported REPLACE/SORTBY adapters.
- [x] Preserve fixed-position 008 semantics instead of converting to the leader-dependent default.
- [x] Run importer and migration tests.

### Task 5: Structural codegen and ordering cleanup

**Files:**
- Modify: `tests/test_codegen_safety.py`
- Modify: `tests/test_task_builder.py`
- Modify: `tests/test_transforms.py`
- Modify: `marcedit_web/lib/codegen_safety.py`
- Modify: `marcedit_web/lib/task_builder.py`
- Modify: `marcedit_web/lib/transforms.py`

- [x] Add RED tests for nested literal rendering, rejection of arbitrary nested objects, record number zero in diagnostics, and source-position-preserving retag behavior.
- [x] Add a strict nested-data literal renderer and use it for structural codegen.
- [x] Replace quadratic inversion counting with an O(n log n) implementation while preserving the public result contract.
- [x] Run codegen, task-builder, transforms, and quick-batch tests.

### Task 6: Final verification and traceability

**Files:**
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`
- Modify: `.tickets/TASK-181-explicit-rda-operations.md`
- Modify: `.tickets/TASK-182-explicit-marc-field-reordering.md`
- Modify: `.tickets/TASK-183-cataloger-operation-reference.md`
- Modify: `.tickets/TASK-184-structural-find-replace-authoring.md`
- Modify: `.tickets/TASK-185-external-find-replace-migration.md`
- Modify: `.tickets/TASK-187-persist-import-diagnostics.md`
- Modify: `.tickets/TASK-188-task-174-review-remediation.md`

- [x] Run focused suites, native compiler freshness, image-only verification, the complete mounted-source Docker suite, and `git diff --check`.
- [x] Record every skip/failure without converting environment limitations into passes.
- [x] Mark tickets Completed only after review finds no unresolved Critical or Important issue.
- [x] Commit remediation separately from checkpoint `c1dab43`.
