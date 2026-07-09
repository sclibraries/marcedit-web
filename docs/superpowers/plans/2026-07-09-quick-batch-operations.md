# Quick Batch Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build TASK-137 quick batch operations on the Tasks page, excluding FOLIO container-code standardization in `035 $9`.

**Architecture:** Add deterministic operation logic in `marcedit_web/lib/quick_batch.py` with request/preview/result dataclasses and pure preview/apply helpers. Add a compact Tasks-page UI that selects an operation, previews record impact, and applies the operation to the loaded `RecordStore` without creating saved task files or generated Python.

**Tech Stack:** Python 3.9, Streamlit, pymarc, pytest, existing `RecordStore`, `session`, `task_diff`, and Tasks-page render patterns.

## Global Constraints

- Ticket: TASK-137 (`.tickets/TASK-137-quick-batch-operations.md`).
- Design spec: `docs/superpowers/specs/2026-07-09-quick-batch-operations-design.md`.
- Exclude FOLIO container code standardization in `035 $9`; that is a separate ticket.
- Operations are one-shot, preview-first, and apply to the whole loaded batch.
- Do not generate saved task files or execute generated Python.
- Advanced conditional workflows remain in the existing task builder/code path.
- Leave unrelated files alone; `missing856.txt` is unrelated and stays untracked.

---

## File Structure

- Create `marcedit_web/lib/quick_batch.py`
  - Owns all quick batch request dataclasses, value lists, preview/apply helpers, and MARC mutation functions.
  - Provides a single operation entrypoint shape:
    - `validate_request(request: QuickBatchRequest) -> str | None`
    - `build_preview(store, request: QuickBatchRequest) -> QuickBatchPreview`
    - `apply_request(store, request: QuickBatchRequest) -> QuickBatchResult`
- Create `tests/test_quick_batch.py`
  - Unit tests for every operation family.
- Modify `marcedit_web/render/tasks.py`
  - Import `quick_batch`.
  - Add `_render_quick_batch_operations()` next to `_render_quick_find_replace()`.
  - Store preview in `st.session_state["quick_batch_preview"]`.
  - Apply updates the current `RecordStore`, clears derived caches, audits `quick-batch-applied`, and reruns.
- Modify `tests/test_tasks.py` or add a small render-focused section if existing fake Streamlit coverage is suitable.
  - Verify quick operations are one-shot UI, preview-first, and do not create saved tasks.
- Modify `.tickets/TASK-137-quick-batch-operations.md`
  - Mark In-Progress at implementation start and Completed after verification.

---

### Task 1: Core Quick Batch Library

**Files:**
- Create: `marcedit_web/lib/quick_batch.py`
- Create: `tests/test_quick_batch.py`
- Modify: `.tickets/TASK-137-quick-batch-operations.md`

**Interfaces:**
- Produces:
  - `OperationKind = Literal["leader", "008-form", "040-cleanup", "856-url", "035-oclc", "9xx-delete", "655-cleanup"]`
  - `@dataclass(frozen=True) QuickBatchRequest`
  - `@dataclass QuickBatchPreview`
  - `@dataclass QuickBatchResult`
  - `validate_request(request) -> str | None`
  - `build_preview(store, request) -> QuickBatchPreview`
  - `apply_request(store, request) -> QuickBatchResult`
  - `LEADER_VALUE_OPTIONS: dict[str, tuple[CodeOption, ...]]`
  - `FORM_OF_ITEM_OPTIONS: tuple[CodeOption, ...]`
- Consumes:
  - `store.iter_records()`, `store.replace_all(records)`.
  - `pymarc.Record`, `pymarc.Field`, `pymarc.Subfield`.

- [ ] **Step 1: Mark TASK-137 In-Progress**

Edit `.tickets/TASK-137-quick-batch-operations.md`:

```markdown
Status: In-Progress
```

- [ ] **Step 2: Write failing tests for the operation library**

Create `tests/test_quick_batch.py` with tests named:

```python
def test_leader_request_sets_safe_position_on_every_record(make_record): ...
def test_leader_request_rejects_structural_position(make_record): ...
def test_008_form_request_updates_known_position_and_skips_missing_008(make_record): ...
def test_040_cleanup_adds_rda_and_local_modifier_without_duplicates(make_record): ...
def test_856_add_proxy_only_updates_unproxied_urls(make_record): ...
def test_856_remove_proxy_strips_existing_prefix(make_record): ...
def test_856_delete_matching_url_removes_matching_fields(make_record): ...
def test_035_oclc_cleanup_normalizes_and_preserves_035_9(make_record): ...
def test_9xx_delete_exact_tag_and_range(make_record): ...
def test_655_cleanup_adds_standard_field_and_deletes_unwanted_text(make_record): ...
def test_build_preview_reports_changed_and_skipped_counts(tmp_path, make_record): ...
def test_apply_request_replaces_store_records(tmp_path, make_record): ...
```

Use real `RecordStore.from_records(...)` and real `pymarc.Record` objects. Assert changed/skipped counts and specific MARC field values after apply.

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
docker compose exec marcedit-web pytest -ra tests/test_quick_batch.py
```

Expected: FAIL during import because `marcedit_web.lib.quick_batch` does not exist.

- [ ] **Step 4: Implement `quick_batch.py` minimally**

Create the module with:

```python
@dataclass(frozen=True)
class CodeOption:
    code: str
    label: str

@dataclass(frozen=True)
class QuickBatchRequest:
    kind: str
    leader_position: str = ""
    leader_value: str = ""
    form_of_item: str = ""
    agency_code: str = ""
    proxy_prefix: str = ""
    url_contains: str = ""
    tag: str = ""
    genre_term: str = ""
    genre_source: str = "lcgft"
    unwanted_text: str = ""

@dataclass
class QuickBatchPreview:
    request: QuickBatchRequest
    total_records: int = 0
    changed_records: int = 0
    skipped_records: int = 0
    warnings: list[str] = field(default_factory=list)
    existing_values: dict[str, int] = field(default_factory=dict)
    error: str | None = None

@dataclass
class QuickBatchResult:
    request: QuickBatchRequest
    total_records: int = 0
    changed_records: int = 0
    skipped_records: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
```

Implement each operation as pure mutation of copied records:

- Leader: set `record.leader[int(position)] = value` only for safe positions/options.
- 008 form: use existing `transforms.set_008_form_of_item(record, form)`.
- 040: ensure a 040 exists, append `$e rda` and `$d agency_code` only if absent.
- 856 add/remove/delete: mutate `$u`; delete matching whole 856 fields.
- 035/OCLC: normalize OCLC-like 035 values, remove duplicate OCLC values, leave non-OCLC fields and any `$9` values untouched.
- 9xx: delete exact tag or expand `9XX` wildcard via existing `transforms.delete_tags`.
- 655: add a 655 with selected term/source if absent; delete 655 fields whose subfield text contains unwanted text.

- [ ] **Step 5: Run tests to verify GREEN**

Run:

```bash
docker compose exec marcedit-web pytest -ra tests/test_quick_batch.py
```

Expected: all tests in `tests/test_quick_batch.py` pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add .tickets/TASK-137-quick-batch-operations.md marcedit_web/lib/quick_batch.py tests/test_quick_batch.py
git commit -m "feat: add quick batch operation library"
```

---

### Task 2: Tasks Page Quick Batch UI

**Files:**
- Modify: `marcedit_web/render/tasks.py`
- Test: `tests/test_tasks.py` or `tests/test_quick_batch_render.py`

**Interfaces:**
- Consumes Task 1:
  - `quick_batch.QuickBatchRequest`
  - `quick_batch.build_preview(store, request)`
  - `quick_batch.apply_request(store, request)`
  - value option dictionaries for dropdown labels.
- Produces:
  - `_render_quick_batch_operations() -> None`
  - `_build_and_store_quick_batch_preview(request) -> None`
  - `_render_quick_batch_preview(preview) -> None`
  - `_apply_quick_batch_preview(preview) -> None`

- [ ] **Step 1: Write failing render tests**

Add tests that import `marcedit_web.render.tasks` with fake Streamlit and assert:

```python
def test_quick_batch_hidden_without_upload(monkeypatch): ...
def test_quick_batch_preview_required_before_apply(monkeypatch): ...
def test_quick_batch_apply_replaces_store_and_does_not_save_task(monkeypatch): ...
```

The fake should track calls to `selectbox`, `button`, `metric`, `success`, and verify `task_db.save_task` is not called.

- [ ] **Step 2: Run render tests to verify RED**

Run:

```bash
docker compose exec marcedit-web pytest -ra tests/test_tasks.py -k quick_batch
```

Expected: FAIL because quick batch render helpers do not exist.

- [ ] **Step 3: Implement Tasks-page UI**

Modify `render()` after `_render_quick_find_replace()` call to call:

```python
_render_quick_batch_operations()
```

Add an expander:

```python
with st.expander("Quick batch operations (no saved task)", expanded=False):
    st.caption("Run a preview-first canned operation across the loaded batch. Nothing is saved to your task list.")
```

Render operation selector and operation-specific fields. Preview stores
`st.session_state["quick_batch_preview"]`. Apply calls
`quick_batch.apply_request(store, preview.request)`, clears
`issues_cache`, audits `quick-batch-applied`, and `st.rerun()`.

- [ ] **Step 4: Run render tests to verify GREEN**

Run:

```bash
docker compose exec marcedit-web pytest -ra tests/test_tasks.py -k quick_batch
```

Expected: quick batch render tests pass.

- [ ] **Step 5: Run related suites**

Run:

```bash
docker compose exec marcedit-web pytest -ra tests/test_quick_batch.py tests/test_tasks.py tests/test_task_builder.py tests/test_batch_replace.py
```

Expected: all pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add marcedit_web/render/tasks.py tests/test_tasks.py
git commit -m "feat: add quick batch operations UI"
```

---

### Task 3: Completion, Docs, and Verification

**Files:**
- Modify: `.tickets/TASK-137-quick-batch-operations.md`
- Optional modify: `docs/superpowers/specs/2026-07-09-quick-batch-operations-design.md` only if implementation intentionally deviates.

**Interfaces:**
- Consumes Task 1 and Task 2 committed work.
- Produces completed ticket status and verified push-ready tree.

- [ ] **Step 1: Update ticket status**

Edit `.tickets/TASK-137-quick-batch-operations.md`:

```markdown
Status: Completed (2026-07-09: implemented preview-first Quick batch operations for Leader, 008 form of item, 040 cleanup, 856 URL tools, OCLC 035 cleanup excluding 035 $9, local 9xx cleanup, and 655 cleanup; verified with focused tests and full suite.)
```

- [ ] **Step 2: Run full verification**

Run:

```bash
docker compose exec marcedit-web pytest -ra
env PYTHONPATH=. pytest -ra tests/test_deploy_units.py tests/test_docker_compose_config.py
git diff --check origin/main...HEAD
git status --short --branch
```

Expected:

- Container suite passes; deploy/Docker tests may skip inside the container as usual.
- Host deploy/Docker tests pass.
- `git diff --check origin/main...HEAD` prints no whitespace errors.
- Only intentionally untracked `missing856.txt` remains untracked.

- [ ] **Step 3: Commit completion**

```bash
git add .tickets/TASK-137-quick-batch-operations.md docs/superpowers/specs/2026-07-09-quick-batch-operations-design.md
git commit -m "docs: complete quick batch operations ticket"
```

---

## Self-Review

- Spec coverage:
  - Leader, 008, 040, 856, 035/OCLC, 9xx, and 655 are all covered in Task 1 tests and implementation.
  - Tasks-page one-shot UI, preview-first flow, no saved task file, and full-batch apply are covered in Task 2.
  - FOLIO `035 $9` container code workflow is explicitly excluded.
- Completeness scan: no unresolved markers remain; each task has concrete files, commands, and expected outcomes.
- Type consistency:
  - `QuickBatchRequest`, `QuickBatchPreview`, `QuickBatchResult`, `build_preview`, and `apply_request` are introduced in Task 1 and consumed in Task 2.
