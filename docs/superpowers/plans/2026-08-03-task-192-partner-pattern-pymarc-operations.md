# TASK-192 Partner-Pattern pymarc Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-192](../../../.tickets/TASK-192-partner-pattern-pymarc-operations.md)

**Goal:** Convert proven repeated partner-task patterns into deterministic, editable pymarc operations without changing the existing `copy-field` contract or guessing unsupported external semantics.

**Architecture:** Keep operation definitions in `task_builder.Operation` and compile them through the existing `render_ops_to_python` path. Put record mutation and preview counting in a pure helper module that accepts a `pymarc.Record`; re-export only the public entry points through `transforms.py` so the sandbox sees one execution surface. Extend the importer with table-driven, contiguous pattern adapters and preserve unresolved source lines as actionable migration blockers.

**Tech Stack:** Python 3.9, pymarc, SQLite-backed task storage, Streamlit form authoring, pytest, existing subprocess sandbox and corpus audit scripts.

## Global Constraints

- Never infer undocumented external flags, loop semantics, or missing `TASK_LIST` dependencies.
- Existing `copy-field` saved parameters, generated code, and AI-draft behavior remain byte-compatible.
- New operation kinds are excluded from both AI-draft schemas before palette exposure.
- All user values pass through `lit()`/`data_lit()` at code-generation boundaries.
- Preview and execution call the same pure transformation engine.
- Per-record and batch expansion bounds fail the complete submission and discard candidate output.
- Supported runtime is Python 3.9; no new dependency is added.

---

### Task 1: Characterize existing copy-field and corpus evidence

**Files:**
- Modify: `tests/test_task_builder.py`
- Modify: `tests/test_transforms.py`
- Modify: `tests/test_external_task_migration.py`
- Modify: `scripts/audit_external_task_corpus.py`
- Create: `tests/fixtures/external_task_corpus/task-191-converted-blocker-report.json`
- Test: `tests/fixtures/external_task_migration/`

**Interfaces:**
- Consumes: current `copy-field` operation, TASK-191 corpus audit output.
- Produces: regression tests and a checked-in derivation of the 166 unique unresolved source-line count for later adapter work.

- [ ] **Step 1: Add failing characterization tests** for the existing `copy-field` saved shape, predicate behavior, output ordering, generated imports, and AI schema.
- [ ] **Step 2: Run** `pytest -q tests/test_task_builder.py tests/test_ai_task_draft.py tests/test_external_task_migration.py`; confirm the new tests fail only because the assertions are not yet present.
- [ ] **Step 3: Add the corpus-report derivation** that counts distinct non-converted `source_line` values from the TASK-191 audit JSON and writes the converted/blocker report without including private record content.
- [ ] **Step 4: Run** `python scripts/audit_external_task_corpus.py --help` and the focused corpus command used by TASK-191; verify zero unclassified lines and zero blocker rows without a next action.
- [ ] **Step 5: Commit** `test: characterize partner pattern contracts`.

### Task 2: Add pure pymarc partner operations and bounded preview accounting

**Files:**
- Create: `marcedit_web/lib/partner_operations.py`
- Modify: `marcedit_web/lib/transforms.py`
- Test: `tests/test_partner_operations.py`

**Interfaces:**
- Consumes: `pymarc.Record`, structured predicates already accepted by `field_predicates`.
- Produces: `build_fields_for_matches(record, ...)`, `copy_fields_with_policy(record, ...)`, `apply_institution_profile(record, ...)`, and an immutable result containing inspected/matched/created/replaced/skipped counts.

- [ ] **Step 1: Write failing tests** for zero/one/multiple source fields, missing source behavior, duplicate source occurrences, destination collision policies (`append`, `replace`, `skip`), and preserved field order.
- [ ] **Step 2: Write failing tests** proving a per-record and batch expansion limit aborts the whole operation and leaves the candidate record unchanged.
- [ ] **Step 3: Implement** the pure helpers with explicit enums/validation, `pymarc.Field` cloning, and a single bounded mutation path. Reject unknown policies and malformed templates before mutation.
- [ ] **Step 4: Re-export** only the public helpers from the bottom of `transforms.py`; keep `partner_operations.py` a leaf module so imports cannot cycle.
- [ ] **Step 5: Run** `pytest -q tests/test_partner_operations.py tests/test_transforms.py`; expect all new and existing tests to pass.
- [ ] **Step 6: Commit** `feat: add bounded partner pymarc operations`.

### Task 3: Add structured operation palette/code generation

**Files:**
- Modify: `marcedit_web/lib/task_builder.py`
- Modify: `marcedit_web/lib/task_authoring.py`
- Modify: `marcedit_web/lib/codegen_safety.py` to cover nested dict/list literals used by the new operation payloads
- Test: `tests/test_task_builder.py`, `tests/test_task_authoring.py`

**Interfaces:**
- Consumes: Task 2 helpers.
- Produces: palette kinds `build-fields-from-source`, `copy-fields-with-policy`, and `institution-profile`; each renders through `data_lit()` and round-trips through `# OP:` markers.

- [ ] **Step 1: Add failing palette, validation, form-summary, and round-trip tests** for the three new kinds, including explicit source-missing, occurrence, collision, and expansion parameters.
- [ ] **Step 2: Add code-generation tests** that assert generated source calls only the re-exported helper and contains no raw `repr(dict(...))` bypass.
- [ ] **Step 3: Implement the palette entries and renderer branches**, preserving all existing palette order-independent semantics and using `data_lit()` for nested mappings/lists.
- [ ] **Step 4: Add editor normalization and cataloger-facing summaries** for the new parameters; unknown policy values must return validation errors instead of destructive defaults.
- [ ] **Step 5: Run** `pytest -q tests/test_task_builder.py tests/test_task_authoring.py`; verify existing operation snapshots remain unchanged.
- [ ] **Step 6: Commit** `feat: expose partner operations in task authoring`.

### Task 4: Add fail-closed external pattern adapters

**Files:**
- Modify: `marcedit_web/lib/external_task_migration.py`
- Modify: `marcedit_web/lib/marcedit_import.py`
- Modify: `marcedit_web/schemas/external-task-compatibility-v1.json`
- Test: `tests/test_external_task_migration.py`, `tests/test_marcedit_import.py`

**Interfaces:**
- Consumes: Task 2/3 operation shapes and existing `ADAPTER_REGISTRY` dispatch.
- Produces: contiguous adapters for only the reviewed 856 and 945–949 signatures; unresolved ranges retain every source line, fingerprint, reason, and next action.

- [ ] **Step 1: Add failing golden tests** for each accepted source range and for near-miss flags/columns that must remain blockers.
- [ ] **Step 2: Implement registry-driven dispatch** through `ADAPTER_REGISTRY`; remove hard-coded adapter branching and reject overlapping pattern matches.
- [ ] **Step 3: Emit one consolidated native operation per proven range** with per-line provenance and preserve source ordering.
- [ ] **Step 4: Add TASK_LIST missing-dependency blockers** that ask the cataloger to import/select the dependency and never resolve by display name.
- [ ] **Step 5: Run** `pytest -q tests/test_external_task_migration.py tests/test_marcedit_import.py`; regenerate the partner report and inspect all blocker next actions.
- [ ] **Step 6: Commit** `feat: migrate proven partner task patterns`.

### Task 5: Preserve the AI boundary and update reference documentation

**Files:**
- Modify: `marcedit_web/lib/ai_task_draft.py`
- Modify: `marcedit_web/lib/gemini_task_draft.py`
- Modify: `docs/operation-reference.md`
- Modify: `docs/external-task-migration.md`
- Test: `tests/test_ai_task_draft.py`, `tests/test_gemini_task_draft.py`, `tests/test_operation_reference_registry.py`

**Interfaces:**
- Consumes: new palette kinds and importer summaries.
- Produces: explicit unsupported-kind gates before parameter validation; cataloger documentation for each new operation and migration recommendation.

- [ ] **Step 1: Add failing tests** proving new kinds are absent from AI validation and Gemini prompt schemas while existing `copy-field` remains accepted with its current predicate shape.
- [ ] **Step 2: Add the new kinds to `_UNSUPPORTED_AI_OPERATION_KINDS`** and make Gemini consult `is_operation_kind_supported` for the same set.
- [ ] **Step 3: Document preview counts, bound failures, source provenance, and the open equivalent of every accepted partner pattern.
- [ ] **Step 4: Run** the focused AI/reference suites and the full Python 3.9 Docker suite; report every skip.
- [ ] **Step 5: Commit** `docs: document partner operation migration and AI boundary`.

### Task 6: Corpus and release verification

**Files:**
- Modify: `.tickets/TASK-192-partner-pattern-pymarc-operations.md`
- Modify: `tests/fixtures/external_task_corpus/task-191-converted-blocker-report.json`
- Test: all TASK-192-focused tests and Docker suite

- [ ] **Step 1:** Regenerate the complete 49-archive report and verify 1,239 instructions are classified as converted or actionable blockers.
- [ ] **Step 2:** Run focused tests, full source-mounted tests, and Python 3.9 Docker tests; record exact pass/skip/failure counts.
- [ ] **Step 3:** Request independent code review; resolve all Critical/Important findings.
- [ ] **Step 4:** Update the ticket to `Completed` only after tests and review pass, then commit the ticket/report update.
