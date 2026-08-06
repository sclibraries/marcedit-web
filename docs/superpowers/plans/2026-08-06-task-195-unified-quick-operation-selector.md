# TASK-195 Unified Quick Operation Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-195](../../../.tickets/TASK-195-focused-quick-field-changes.md)

**Goal:** Fix the focused-preview session-key crash and replace the three competing Quick-operation entry points with one alphabetized selector containing all 18 operations.

**Architecture:** Keep `BatchReplaceRequest`, `QuickFieldChangeRequest`, and `QuickBatchRequest` execution unchanged. Add a small presentation-only registry and router in `render/tasks.py`; pass the selected operation into the existing focused and specialized renderers so neither renders a nested operation selector. Clear every engine's preview/export artifacts whenever the selected operation changes.

**Tech Stack:** Python 3.9, Streamlit 1.50, existing Quick renderers and sandbox runners, pytest, Docker Compose.

## Global Constraints

- TASK-195 remains `In-Progress` until the authenticated browser scenarios pass.
- Exactly one Quick operation is selected, previewed, and applied at a time.
- The selector contains exactly one Find and replace entry, all nine focused field changes, and all eight specialized Quick operations.
- Labels are sorted by cataloger-facing text; engine identifiers never appear in the UI.
- Find and replace and specialized controls render only after their entry is selected; no nested operation dropdown remains.
- The three existing request types, validation rules, sandbox paths, apply paths, audit events, snapshots, job-file versions, and exports remain authoritative.
- Switching any operation label clears preview and export state for all three engines before rendering the new controls.
- Harmless keyed form values remain available when a cataloger returns to an operation.
- Widget keys and stored domain-object keys are always distinct.
- No dependency, database schema, authorization, AI, task compiler, or external-import behavior changes.
- This amendment supersedes the original plan's presentation-only clauses that
  keep Quick Find and replace separate and let the focused and specialized
  renderers choose their own operation. All original execution, validation,
  persistence, and verification constraints remain in force.

---

### Task 1: Separate the Preview Widget and Domain-Object Keys

**Files:**
- Modify: `marcedit_web/render/quick_field_changes.py:27-33`
- Modify: `tests/test_quick_field_changes_render.py:22-65`

**Interfaces:**
- Consumes: existing `FakeStreamlit` renderer test boundary.
- Produces: distinct `K_PREVIEW = "quick_field_change_preview"` and `K_PREVIEW_BUTTON = "quick_field_change_preview_button"` constants.

- [ ] **Step 1: Write a stateful Streamlit RED regression**

Make the fake reproduce Streamlit's keyed-button behavior and assert the object key cannot be reused:

```python
class StatefulButtonFake(FakeStreamlit):
    def button(self, label, *, key, **kwargs):
        pressed = super().button(label, key=key, **kwargs)
        self.session_state[key] = pressed
        return pressed


def test_preview_button_cannot_replace_the_preview_object(monkeypatch):
    fake = StatefulButtonFake()

    _render(monkeypatch, fake)

    assert renderer.K_PREVIEW != renderer.K_PREVIEW_BUTTON
    assert fake.session_state[renderer.K_PREVIEW_BUTTON] is False
    assert renderer.K_PREVIEW not in fake.session_state
```

This test encodes why the keys differ: before the fix, the initial button render stores `False` under `quick_field_change_preview`, then `_request_is_current()` attempts `preview.error` on that Boolean.

- [ ] **Step 2: Run the regression and confirm RED**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_quick_field_changes_render.py::test_preview_button_cannot_replace_the_preview_object
```

Expected: FAIL because `K_PREVIEW` and `K_PREVIEW_BUTTON` are identical, or because rendering reaches `False.error`.

- [ ] **Step 3: Assign the Preview button its own key**

Use these exact constants:

```python
K_PREVIEW = KEY_PREFIX + "preview"
K_PREVIEW_BUTTON = KEY_PREFIX + "preview_button"
```

Do not rename `K_PREVIEW`; existing preview cleanup and adoption use that stored-object key.

- [ ] **Step 4: Run focused renderer tests GREEN**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_quick_field_changes_render.py
```

Expected: all pass, zero skipped.

- [ ] **Step 5: Commit the crash fix**

```bash
git add marcedit_web/render/quick_field_changes.py tests/test_quick_field_changes_render.py
git commit -m "fix: separate quick preview widget state"
```

---

### Task 2: Route All Quick Operations Through One Dropdown

**Files:**
- Modify: `marcedit_web/render/tasks.py:1437-1471`
- Modify: `marcedit_web/render/tasks.py:4020-4124`
- Modify: `marcedit_web/render/tasks.py:4511-4570`
- Modify: `marcedit_web/render/quick_field_changes.py:699-785`
- Modify: `tests/test_task_quick_field_changes.py:88-120`
- Modify: `tests/test_quick_field_changes_render.py`
- Modify: `tests/test_quick_batch.py`
- Modify: `tests/test_batch_replace.py`

**Interfaces:**
- Consumes: `quick_field_changes_render.OPERATION_KINDS`, `_QB_OPERATION_LABELS`, `_render_quick_find_replace()`, `_render_quick_batch_operations()`, and `render_common_field_changes()`.
- Produces: `_quick_operation_entries() -> tuple[tuple[str, str], ...]`, `_clear_quick_operation_state() -> None`, `_render_quick_batch_operations(kind: str) -> None`, and `render_common_field_changes(store, *, operation_kind: str, job_file_id, job_file_version_id, on_apply, preview_builder=None) -> None`.

- [ ] **Step 1: Write registry and routing RED tests**

Replace the old “mounts between existing flows” assertion with an exact registry contract:

```python
EXPECTED_QUICK_LABELS = (
    "008 form of item",
    "040 cleanup",
    "655 genre/form cleanup",
    "856 URL tools",
    "Add field",
    "Add subfield",
    "Copy field",
    "Delete field",
    "Delete subfield",
    "Find and replace",
    "Leader value",
    "Local 9xx cleanup",
    "Move or retag field",
    "OCLC 035 cleanup",
    "Remove exact duplicate fields",
    "Reorder fields by canonical tag order",
    "Set indicators",
    "Swap field occurrences",
)


def test_quick_operation_registry_is_complete_unique_and_alphabetical():
    entries = tasks_render._quick_operation_entries()
    assert tuple(label for _identifier, label in entries) == EXPECTED_QUICK_LABELS
    assert len({identifier for identifier, _label in entries}) == 18
```

Add parameterized routing tests selecting one identifier from each engine and asserting only its renderer is called:

```python
class _QuickRouterFake:
    def __init__(self, selected, *, session_state=None):
        self.selected = selected
        self.session_state = dict(session_state or {})
        self.errors = []

    def selectbox(self, label, *, options, format_func, key, **_kwargs):
        assert label == "Quick operation"
        assert self.selected in options
        self.session_state[key] = self.selected
        return self.selected

    def error(self, message):
        self.errors.append(str(message))


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        ("find-replace", ["find"]),
        ("field:delete-field", ["field", "field-export"]),
        ("batch:035-oclc", ["batch"]),
    ],
)
def test_quick_router_renders_only_the_selected_engine(monkeypatch, selected, expected):
    calls = []
    fake_st = _QuickRouterFake(selected)
    monkeypatch.setattr(tasks_render, "st", fake_st)
    monkeypatch.setattr(tasks_render.session, "has_upload", lambda: True)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: object())
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)
    monkeypatch.setattr(tasks_render, "_render_quick_find_replace", lambda: calls.append("find"))
    monkeypatch.setattr(
        tasks_render.quick_field_changes_render,
        "render_common_field_changes",
        lambda *args, **kwargs: calls.append("field"),
    )
    monkeypatch.setattr(
        tasks_render,
        "_render_quick_field_change_export",
        lambda: calls.append("field-export"),
    )
    monkeypatch.setattr(
        tasks_render,
        "_render_quick_batch_operations",
        lambda kind: calls.append("batch"),
    )

    tasks_render._render_quick_ops_mode()

    assert calls == expected
```

Add tests proving Find and replace and specialized renderers no longer create an `Operation` selectbox or their old outer expanders. Add a focused-renderer test that supplies `operation_kind="delete-field"` and asserts no operation selectbox is emitted.

- [ ] **Step 2: Write operation-switch cleanup RED tests**

Seed all three preview keys and both disk-backed export keys, select a different operation than `_K_QUICK_OPERATION_ACTIVE`, and assert every cleanup boundary receives its artifact before the selected renderer runs:

```python
def test_switching_quick_operation_cleans_all_preview_and_export_state(monkeypatch):
    events = []
    find_preview = object()
    field_preview = object()
    batch_preview = object()
    field_export = {"path": "/tmp/field-export", "temporary": False}
    batch_export = {"path": "/tmp/batch-export", "temporary": False}
    fake_st = _QuickRouterFake(
        "field:add-field",
        session_state={
            tasks_render._K_QUICK_OPERATION_ACTIVE: "find-replace",
            tasks_render._K_BR_PREVIEW: find_preview,
            tasks_render._K_QFC_PREVIEW: field_preview,
            tasks_render._K_QB_PREVIEW: batch_preview,
            tasks_render._K_QFC_EXPORT: field_export,
            tasks_render._K_QB_EXPORT: batch_export,
            "br_tag": "035",
            "qb_040_agency": "MNS",
        },
    )
    monkeypatch.setattr(tasks_render, "st", fake_st)
    monkeypatch.setattr(
        tasks_render.batch_replace,
        "cleanup_preview",
        lambda value: events.append(("find", value)),
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "cleanup_artifact",
        lambda value: events.append(("field", value)),
    )
    monkeypatch.setattr(
        tasks_render.quick_batch,
        "cleanup_preview",
        lambda value: events.append(("batch", value)),
    )
    exports = []
    monkeypatch.setattr(
        tasks_render,
        "_cleanup_disk_backed_export",
        lambda value: exports.append(value),
    )
    monkeypatch.setattr(tasks_render.session, "has_upload", lambda: True)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: object())
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)
    monkeypatch.setattr(
        tasks_render.quick_field_changes_render,
        "render_common_field_changes",
        lambda *args, **kwargs: None,
    )

    tasks_render._render_quick_ops_mode()

    assert events == [
        ("find", find_preview),
        ("field", field_preview),
        ("batch", batch_preview),
    ]
    assert exports == [field_export, batch_export]
    assert tasks_render._K_BR_PREVIEW not in fake_st.session_state
    assert tasks_render._K_QFC_PREVIEW not in fake_st.session_state
    assert tasks_render._K_QB_PREVIEW not in fake_st.session_state
    assert tasks_render._K_QFC_EXPORT not in fake_st.session_state
    assert tasks_render._K_QB_EXPORT not in fake_st.session_state
    assert fake_st.session_state["br_tag"] == "035"
    assert fake_st.session_state["qb_040_agency"] == "MNS"
```

The fake must preserve unrelated form keys such as `br_tag` and `qb_040_agency`; assert they remain after cleanup.

- [ ] **Step 3: Run routing tests and confirm RED**

Run:

```bash
PYTHONPATH=. pytest -q \
  tests/test_task_quick_field_changes.py \
  tests/test_quick_field_changes_render.py \
  tests/test_quick_batch.py \
  tests/test_batch_replace.py
```

Expected: new tests fail because three independent selectors/forms still render and the unified registry/router does not exist.

- [ ] **Step 4: Implement the presentation-only registry and cleanup boundary**

Use namespaced identifiers so labels never control execution:

```python
_K_QUICK_OPERATION_SELECTOR = "quick_operation_selector"
_K_QUICK_OPERATION_ACTIVE = "quick_operation_active"


def _quick_operation_entries() -> tuple[tuple[str, str], ...]:
    entries = [("find-replace", "Find and replace")]
    entries.extend(
        (f"field:{kind}", label)
        for label, kind in quick_field_changes_render.OPERATION_KINDS.items()
    )
    entries.extend(
        (f"batch:{kind}", label)
        for kind, label in _QB_OPERATION_LABELS.items()
    )
    return tuple(sorted(entries, key=lambda item: item[1].casefold()))
```

Implement `_clear_quick_operation_state()` by popping and cleaning `_K_BR_PREVIEW`, `_K_QFC_PREVIEW`, `_K_QB_PREVIEW`, `_K_QFC_EXPORT`, `_K_QB_EXPORT`, `_K_QFC_DOWNLOAD_READY`, and `K_QB_DOWNLOAD_READY`. Call `_cleanup_disk_backed_export()` for both export objects. Do not remove request-form widget keys.

In `_render_quick_ops_mode()`, render one `st.selectbox("Quick operation", ...)`. Compare its identifier with `_K_QUICK_OPERATION_ACTIVE`; on a real change, clear all Quick evidence before routing, then store the new active identifier. Route by exact prefix:

```python
if selected == "find-replace":
    _render_quick_find_replace()
elif selected.startswith("field:"):
    quick_field_changes_render.render_common_field_changes(
        session.current_store(),
        operation_kind=selected[len("field:"):],
        job_file_id=job_file_id,
        job_file_version_id=job_file_version_id,
        on_apply=_apply_quick_field_change_preview,
        preview_builder=_build_quick_field_change_preview,
    )
    _render_quick_field_change_export()
else:
    _render_quick_batch_operations(selected[len("batch:"):])
```

Python 3.9 does not provide `str.removeprefix`; retain the two explicit prefix slices shown above. Reject an unknown identifier with a bounded `st.error` and render no operation controls.

- [ ] **Step 5: Remove nested selectors without changing request construction**

Change the focused renderer to accept the canonical kind and validate it against `OPERATION_KINDS.values()` before calling `_render_request(kind)`. Remove its `_choice("Operation", ...)` call. Retain `EXPECTED_LABELS` and `OPERATION_KINDS` as the registry source and documentation contract.

Change `_render_quick_batch_operations(kind)` to validate `kind in _QB_OPERATION_LABELS`, render its caption and `_quick_batch_request_from_widgets(kind)` inline, and retain the existing Preview, Reset, evidence, and export calls. Remove only the outer expander and inner operation selectbox.

Render `_render_quick_find_replace()` inline after selection by removing only its outer expander. Keep all `BatchReplaceRequest` controls and Preview/Apply behavior unchanged.

- [ ] **Step 6: Run focused tests GREEN**

Run:

```bash
PYTHONPATH=. pytest -q \
  tests/test_task_quick_field_changes.py \
  tests/test_quick_field_changes_render.py \
  tests/test_quick_field_change_runner.py \
  tests/test_quick_field_changes.py \
  tests/test_quick_batch.py \
  tests/test_batch_replace.py
```

Expected: all pass, zero skipped on Linux/Docker. Report any platform-specific sandbox failure separately rather than describing it as a pass.

- [ ] **Step 7: Commit the unified selector**

```bash
git add \
  marcedit_web/render/tasks.py \
  marcedit_web/render/quick_field_changes.py \
  tests/test_task_quick_field_changes.py \
  tests/test_quick_field_changes_render.py \
  tests/test_quick_batch.py \
  tests/test_batch_replace.py
git commit -m "feat: unify quick operation selection"
```

---

### Task 3: Update Guidance and Verify the Authenticated Workflow

**Files:**
- Modify: `docs/operation-reference.md`
- Modify: `marcedit_web/lib/operation_reference.py`
- Modify: `tests/test_operation_reference_registry.py`
- Modify: `.tickets/TASK-195-focused-quick-field-changes.md`

**Interfaces:**
- Consumes: Task 2's unified registry and existing `QUICK_CHANGE_REFERENCE`.
- Produces: cataloger guidance that names the single dropdown and completion evidence only after authenticated browser acceptance.

- [ ] **Step 1: Write documentation RED assertions**

Require the generated Quick guidance to contain “Quick operation,” “Find and replace,” and language stating that only the selected operation's controls are shown. Keep all existing operation-specific coverage assertions.

Run:

```bash
PYTHONPATH=. pytest -q tests/test_operation_reference_registry.py -k quick
```

Expected: FAIL because the current guidance describes separate Quick entry points.

- [ ] **Step 2: Update the cataloger guidance**

Explain the workflow in this order: upload/open a MARC file, open Tasks → Quick changes, choose one entry from **Quick operation**, complete the displayed controls, Preview, review evidence, and Apply. State that changing the operation discards preview evidence but retains harmless form entries.

- [ ] **Step 3: Run authoritative automated verification**

Run the focused suite:

```bash
PYTHONPATH=. pytest -q \
  tests/test_quick_field_selector.py \
  tests/test_quick_field_changes.py \
  tests/test_sandbox.py \
  tests/test_quick_field_change_runner.py \
  tests/test_quick_field_changes_render.py \
  tests/test_task_quick_field_changes.py \
  tests/test_quick_batch.py \
  tests/test_batch_replace.py \
  tests/test_operation_reference_registry.py
```

Then run the full Python 3.9 suite with the repository mounted read-only and a writable data overlay:

```bash
docker compose -p task195-verify -f docker-compose.yml run --rm --no-deps \
  -v "$PWD:/app:ro" \
  -v "$PWD/data:/app/data:rw" \
  marcedit-web python -m pytest -q
```

Record exact pass, fail, and skip counts. A run with skips is not described as simply passing.

- [ ] **Step 4: Run authenticated browser acceptance on port 8501**

Start the TASK-195 worktree on `localhost:8501` with the configured Google OAuth secrets and approved local reviewer. Upload `tests/fixtures/quick-field-changes/multiple-070-and-856.mrc` and verify:

1. The page renders without the `preview.error` Boolean traceback.
2. Exactly one Quick operation dropdown is visible.
3. Its 18 labels are alphabetical and include Find and replace.
4. Selecting Find and replace shows only its existing controls.
5. Selecting Delete field shows only the focused selector and deletion controls.
6. Selecting OCLC 035 cleanup shows only that specialized operation's controls.
7. Switching after Preview removes old evidence and disables Apply until a new Preview.
8. A focused Preview/Apply changes the intended numbered 856 occurrence.
9. Quick Load produces recoverable history/download evidence.
10. A versioned shared-job file produces a collaborator-visible new version.

- [ ] **Step 5: Request final code review and close only after browser evidence**

Use `superpowers:requesting-code-review`. Review the exact amendment range for widget/domain key collisions, registry omissions or duplicates, stale artifacts, unsafe unknown-ID routing, request-type translation, and accidental MARC-semantic changes. Resolve findings and rerun Steps 3–4.

Only after automated verification, review, and authenticated browser acceptance all pass, set the ticket to `Status: Completed` and record the exact evidence.

- [ ] **Step 6: Commit guidance and completion evidence**

```bash
git add \
  docs/operation-reference.md \
  marcedit_web/lib/operation_reference.py \
  tests/test_operation_reference_registry.py \
  .tickets/TASK-195-focused-quick-field-changes.md
git commit -m "docs: complete unified quick operation workflow"
```

Do not push or merge as part of this plan.
