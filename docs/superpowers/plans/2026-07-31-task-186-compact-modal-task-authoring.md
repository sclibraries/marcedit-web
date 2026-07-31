# Compact Modal Task Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-186](../../../.tickets/TASK-186-compact-modal-task-authoring.md)

**Design:** [TASK-186 design](../specs/2026-07-31-task-186-compact-modal-task-authoring-design.md)

**Goal:** Replace long inline task-operation forms with compact ordered cards and one transactional large dialog whose split Workspace keeps setup controls beside preview evidence.

**Architecture:** Keep `render/tasks.py` as the form-editor coordinator and keep the existing operation dictionaries as the only saved representation. Focused card, dialog, and reference modules own presentation; the dialog deep-copies one operation into session state, places setup and preview together in a responsive 45/55 Workspace when preview applies, and commits only on **Keep in task**. Existing validators, compiler, guided-preview cache, and operation-specific controls remain authoritative, with renderer reruns supplied by the caller so modal interactions use fragment scope safely.

**Tech Stack:** Python 3.9, Streamlit `>=1.50,<2`, pymarc 5.x, pytest 8.x, existing task compiler and subprocess sandbox, SQLite task storage, and Docker Compose.

## Global Constraints

- Implement against [TASK-186](../../../.tickets/TASK-186-compact-modal-task-authoring.md) in an isolated worktree; set the ticket to `In-Progress` only when implementation begins and to `Completed` only after all verification and independent review finish.
- Require `streamlit>=1.50,<2` in both `requirements.txt` and `pyproject.toml`; do not use a version-string comparison in place of the `st.dialog` signature contract.
- Assert at runtime and in tests that `dismissible` exists in `inspect.signature(st.dialog).parameters`; fail loud if the contract is unavailable.
- Open at most one Streamlit dialog per script run. The standalone operation reference is reachable only from the main page; an open Add/Edit dialog renders reference content as a tab and never opens a second dialog.
- Preview-capable operations render setup and preview together in one approximately 45/55 Workspace. Operations without preview use the full Workspace width; no empty preview column is rendered.
- Create the operation dialog at runtime with `st.dialog(title, width="large", dismissible=False)(render_function)` so the title can name Add/Edit and the selected operation.
- Keep operation storage, `# OP:` markers, generated Python, compiler output, preview request identity, database schema, and task ordering semantics unchanged.
- Keep code mode, Quick operations, AI drafting, imported-task semantics, authorization, sharing, workers, services, Compose topology, routes, deployment, cron, and ITS-managed configuration unchanged.
- Preserve invalid, unknown, future-version, custom, and unresolved operations losslessly. Never infer or rewrite their meaning merely to display a card or dialog.
- **Keep in task** may retain an incomplete operation; task-level save and submission must reject every invalid/unresolved operation with its one-based ordinal.
- Existing request-keyed guided preview caching remains authoritative. Card order and modal nonce are never part of preview identity.
- Discarding a modal draft must restore the original card and its original preview status. Preview cache entries created for the discarded request may remain cached but cannot display as current for the restored operation.
- Every operation-specific renderer accepts an optional rerun callable. Inline callers default to app scope; modal callers try fragment scope, catch `streamlit.errors.StreamlitAPIException`, and fall back to app scope.
- Keep, Cancel, destructive Remove confirmation, and any other action that closes a dialog use a full-app rerun.
- Do not add custom JavaScript or attempt programmatic focus. Render the Add selector or first Edit setup control first in DOM order.
- Remain syntactically compatible with Python `>=3.9,<3.10`; do not use `match`, `slots=True`, or Python 3.10-only type syntax in modules without postponed annotations.
- Real files under `MarcEdit Tasks/` and vendor MARC records remain untracked and must not enter commits, fixtures, screenshots, logs, or errors.
- Use TDD for every behavior change: demonstrate the intended RED, implement the minimum GREEN, run focused regressions, and commit at each task boundary.
- Report every pytest skip and its reason. “Tests pass” is false when a skip is unreported.

---

## File Map

- Modify `requirements.txt`: raise the Streamlit floor to `1.50`.
- Modify `pyproject.toml`: raise the Streamlit floor to `1.50`.
- Modify `marcedit_web/lib/task_authoring.py`: make palette-required, unknown, and unresolved validation consistent across cards, save, and marker-aware submission preflight.
- Modify `marcedit_web/render/task_authoring.py`: route all eight operation-control reruns through an optional caller-supplied callable.
- Create `marcedit_web/render/task_operation_reference.py`: alphabetical/filterable reference entries and one shared entry renderer for standalone-dialog and in-operation-tab use.
- Create `marcedit_web/render/task_operation_cards.py`: pure card view models plus compact card rendering and confirmed remove/reorder/edit actions.
- Create `marcedit_web/render/task_operation_dialog.py`: modal state, draft transitions, dialog capability preflight, safe fragment rerun, split setup/preview Workspace, secondary technical/reference tabs, and dynamic wrapper invocation.
- Modify `marcedit_web/render/tasks.py`: replace inline operation forms with cards/buttons, invoke one active dialog, retain task-level save/cancel, and keep code mode unchanged.
- Modify `tests/test_task_authoring.py`: required/unknown/unresolved validation and submission-preflight behavior.
- Modify `tests/test_task_authoring_render.py`: injected rerun behavior for all eight existing interaction sites.
- Create `tests/test_task_operation_reference.py`: alphabetical/filter behavior and shared-content rendering.
- Create `tests/test_task_operation_cards.py`: summary, target, validation, preview, reorder, and removal behavior.
- Create `tests/test_task_operation_dialog.py`: state isolation, contract checks, fallback rerun, split Workspace layout, secondary tabs, one-dialog invocation, and cancellation invariants.
- Modify `tests/test_tasks_workspace_modes.py`: compact editor integration, code-mode characterization, save blocking, and fresh modal namespaces.
- Modify `tests/test_tasks_export.py`: marker-aware invalid-operation submission block and unchanged valid execution path.
- Exercise unchanged `tests/test_task_builder.py`, `tests/test_guided_replace_preview.py`, `tests/test_ai_task_draft.py`, `tests/test_gemini_task_draft.py`, `tests/test_note_task_draft.py`, and `tests/test_marcedit_import.py` as behavior contracts.
- Modify `docs/task-authoring-syntax.md`: explain the compact-card and modal workflow without replacing the operation syntax guide.
- Create `docs/superpowers/evidence/task-186-compact-modal-task-authoring-browser-smoke.md`: synthetic Docker/browser acceptance evidence.
- Modify `.tickets/TASK-186-compact-modal-task-authoring.md`: plan link, state, verification, commits, and review outcome.
- Modify `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`: record TASK-186 completion only after final acceptance.

---

### Task 1: Pin dependencies, validation, and caller-controlled reruns

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Modify: `marcedit_web/lib/task_authoring.py`
- Modify: `marcedit_web/render/task_authoring.py`
- Modify: `tests/test_task_authoring.py`
- Modify: `tests/test_task_authoring_render.py`
- Modify: `.tickets/TASK-186-compact-modal-task-authoring.md`

**Interfaces:**
- Produces: `validate_operation(op, *, validate_raw_syntax=True) -> tuple[str, ...]` that rejects an unknown kind, an `authoring_error`, and empty palette parameters declared `required`, while preserving existing Add/Build/Guided validation.
- Produces: `submission_preflight_issues(body: str) -> tuple[str, ...]` that adds marker-parsed operation validation to existing unresolved Add/Build and empty-find checks.
- Produces: `render_add_field_params(params, *, key_prefix, rerun=None) -> None`.
- Produces: `render_build_field_params(params, *, key_prefix, rerun=None) -> None`.
- Produces: `render_guided_find_replace_params(params, *, key_prefix, rerun=None) -> None`.
- Contract: `rerun=None` resolves to the module's current `st.rerun` at call time so monkeypatches and inline callers retain app-scope behavior.

- [ ] **Step 1: Start the ticketed implementation checkpoint**

Set the ticket fields to:

```markdown
Status: In-Progress

Plan:
- `docs/superpowers/plans/2026-07-31-task-186-compact-modal-task-authoring.md`
```

Run:

```bash
git branch --show-current
git status --short
```

Expected: the implementation runs in the isolated TASK-186 worktree/branch and only ticketed files appear.

- [ ] **Step 2: Write failing dependency and validation tests**

Add to `tests/test_task_authoring.py`:

```python
def test_every_palette_required_value_is_validated_before_save_or_run():
    operation = {"kind": "delete-tag", "params": {"tag": ""}}

    assert task_authoring.validate_operation(operation) == (
        "Tag is required",
    )


def test_unknown_and_unresolved_operations_need_attention_losslessly():
    unknown = {"kind": "future-operation", "params": {"opaque": 1}}
    unresolved = {
        "kind": "build-field",
        "params": {"subfields": [["a", "literal {name}"]]},
        "authoring_error": "cannot convert literal braces",
    }

    assert task_authoring.validate_operation(unknown) == (
        "operation kind is not supported: future-operation",
    )
    assert task_authoring.validate_operation(unresolved) == (
        "cannot convert literal braces",
    )
    assert unknown["params"] == {"opaque": 1}


def test_submission_preflight_reports_marker_operation_ordinal():
    body = '# OP: delete-tag {"tag":""}\ndelete_tags(record, "")'

    assert task_authoring.submission_preflight_issues(body) == (
        "Operation 1: Tag is required",
    )
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_authoring.py::test_every_palette_required_value_is_validated_before_save_or_run \
  tests/test_task_authoring.py::test_unknown_and_unresolved_operations_need_attention_losslessly \
  tests/test_task_authoring.py::test_submission_preflight_reports_marker_operation_ordinal
```

Expected: FAIL because generic/unknown operations currently return no validation errors and submission preflight does not compose all marker validation.

- [ ] **Step 3: Implement minimum palette validation without normalizing storage**

In `marcedit_web/lib/task_authoring.py`, look up the operation kind in `task_builder.OPERATIONS_PALETTE` and apply this order:

```python
authoring_error = op.get("authoring_error")
if authoring_error:
    return (str(authoring_error),)

entry = next(
    (item for item in task_builder.OPERATIONS_PALETTE
     if item["kind"] == kind),
    None,
)
if entry is None:
    return ("operation kind is not supported: {0}".format(kind),)
```

After specialized Add/Build/Guided validation, validate only palette parameters marked `required`. Treat `None`, `""`, and an empty list as missing; use the palette label in `"{label} is required"`. Do not reject `False` or `0`, do not delete unexpected keys from legacy operations, and do not reinterpret custom Python.

Extend `submission_preflight_issues` after parsing form-editable markers:

```python
issues.extend(
    validate_operations([operation.to_dict() for operation in parsed["ops"]])
)
```

Deduplicate identical issue strings while preserving order because the existing empty-find safety check can describe the same operation independently.

- [ ] **Step 4: Write failing rerun-injection characterization tests**

Parameterize the existing fake Streamlit tests in `tests/test_task_authoring_render.py` so each of these eight actions returns `True` once:

```python
INTERACTIONS = (
    ("add-field", "move-subfield"),
    ("add-field", "add-subfield"),
    ("build-field", "move-subfield"),
    ("build-field", "add-subfield"),
    ("build-field", "move-segment"),
    ("build-field", "add-segment"),
    ("guided-find-replace", "enter-raw-regex"),
    ("guided-find-replace", "leave-raw-regex"),
)
```

For every case pass `rerun=lambda: calls.append("rerun")` and assert `calls == ["rerun"]`. Add one default-path test that monkeypatches `renderer.st.rerun` and omits the argument.

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_authoring_render.py -k rerun
```

Expected: FAIL with unexpected keyword argument `rerun`.

- [ ] **Step 5: Route the eight sites through the optional callable**

Add:

```python
from typing import Callable


def _request_rerun(rerun: Optional[Callable[[], None]]) -> None:
    (rerun or st.rerun)()
```

Thread `rerun: Optional[Callable[[], None]] = None` through the three public operation renderers and the private Add/Build helpers that reach a rerun site. Replace exactly the eight current plain `st.rerun()` calls with `_request_rerun(rerun)`. Do not change the four operation-level reruns in `render/tasks.py`; those remain app-scope main-page actions until Task 5 replaces them with cards.

- [ ] **Step 6: Raise the Streamlit floor**

Change exactly:

```text
streamlit>=1.50,<2
```

in `requirements.txt` and the corresponding dependency string in `pyproject.toml`. Do not alter Authlib or any other dependency.

- [ ] **Step 7: Run focused regressions and commit**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_task_authoring.py \
  tests/test_task_authoring_render.py \
  tests/test_tasks_export.py
```

Expected: PASS; report every skip. Then:

```bash
git add requirements.txt pyproject.toml \
  marcedit_web/lib/task_authoring.py \
  marcedit_web/render/task_authoring.py \
  tests/test_task_authoring.py tests/test_task_authoring_render.py \
  .tickets/TASK-186-compact-modal-task-authoring.md
git commit -m "feat: prepare task authoring for modal controls"
```

---

### Task 2: Build the shared operation reference

**Files:**
- Create: `marcedit_web/render/task_operation_reference.py`
- Create: `tests/test_task_operation_reference.py`

**Interfaces:**
- Produces: `reference_entries(*, include_custom: bool, query: str = "") -> list[dict]` returning copied palette entries sorted by displayed label, filtered case-insensitively over label and summary.
- Produces: `render_reference_entry(entry: Mapping[str, Any]) -> None` used by both reference surfaces.
- Produces: `render_reference_browser(*, include_custom: bool, key_prefix: str) -> None` for the standalone dialog body.
- Produces: `open_reference_dialog(*, include_custom: bool) -> None` that invokes one non-dismissible large dynamic dialog.

- [ ] **Step 1: Write failing pure reference tests**

Create `tests/test_task_operation_reference.py`:

```python
from marcedit_web.render import task_operation_reference


def test_reference_entries_are_alphabetical_and_search_label_or_summary():
    entries = task_operation_reference.reference_entries(
        include_custom=False,
    )
    labels = [entry["label"] for entry in entries]

    assert labels == sorted(labels, key=str.casefold)
    assert "Custom Python (advanced)" not in labels
    assert [
        entry["label"]
        for entry in task_operation_reference.reference_entries(
            include_custom=False,
            query="selected MARC value",
        )
    ] == ["Guided find and replace"]


def test_reference_entries_are_copies_not_palette_aliases():
    entries = task_operation_reference.reference_entries(include_custom=True)
    entries[0]["label"] = "changed"

    assert all(
        entry["label"] != "changed"
        for entry in task_builder.OPERATIONS_PALETTE
    )
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_operation_reference.py
```

Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement the pure list and shared entry renderer**

Create the module with no dependency on `render/tasks.py`. `reference_entries` deep-copies `task_builder.OPERATIONS_PALETTE`, excludes `custom` when requested, sorts with `entry["label"].casefold()`, and applies:

```python
needle = query.strip().casefold()
haystack = "{0} {1}".format(entry["label"], entry["summary"]).casefold()
```

`render_reference_entry` renders the label, stable kind, and summary. When `kind` is `add-field`, `build-field`, or `guided-find-replace`, include a link/caption naming `docs/task-authoring-syntax.md`; do not invent behavior absent from the palette or syntax guide.

- [ ] **Step 3: Write and implement standalone rendering tests**

Add a fake Streamlit test that records `text_input`, rendered entries, and dialog arguments. Assert:

```python
assert dialog_calls == [{
    "title": "Operation reference",
    "width": "large",
    "dismissible": False,
}]
assert rendered_labels == sorted(rendered_labels, key=str.casefold)
```

Implement `open_reference_dialog` with a runtime wrapper, not a static decorator:

```python
def open_reference_dialog(*, include_custom: bool) -> None:
    def render() -> None:
        render_reference_browser(
            include_custom=include_custom,
            key_prefix="tasks_operation_reference",
        )

    st.dialog(
        "Operation reference",
        width="large",
        dismissible=False,
    )(render)()
```

This function is called only when no operation dialog is active.

- [ ] **Step 4: Verify and commit**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_task_operation_reference.py \
  tests/test_task_builder.py
```

Expected: PASS; report every skip. Then:

```bash
git add marcedit_web/render/task_operation_reference.py \
  tests/test_task_operation_reference.py
git commit -m "feat: add shared task operation reference"
```

---

### Task 3: Build compact operation cards

**Files:**
- Create: `marcedit_web/render/task_operation_cards.py`
- Create: `tests/test_task_operation_cards.py`

**Interfaces:**
- Produces: immutable `OperationCardView(position, kind, label, summary, target, validation_status, validation_errors, preview_status)`.
- Produces: `operation_card_view(operation, *, position, store, previews) -> OperationCardView`.
- Produces: `move_operation(operations, index, delta) -> list[dict]` without mutating the input.
- Produces: `remove_operation(operations, index) -> list[dict]` without mutating the input.
- Produces: `render_operation_cards(operations, *, store, previews, on_edit, on_change) -> None`.

- [ ] **Step 1: Write failing card-model tests**

Create `tests/test_task_operation_cards.py` with valid Add, Build, Guided, generic, unknown, and unresolved operations. Pin these outcomes:

```python
def test_guided_card_uses_plain_summary_target_and_request_keyed_preview():
    operation = guided_operation(tag="035", subfield="a")
    preview = current_preview_for(operation)

    view = task_operation_cards.operation_card_view(
        operation,
        position=2,
        store=STORE,
        previews={guided_replace_preview.preview_cache_key(operation): preview},
    )

    assert view.position == 2
    assert view.label == "Guided find and replace"
    assert view.target == "035 $a"
    assert view.validation_status == "Valid"
    assert view.preview_status == "Current"
    assert "Keep text before and after" in view.summary


def test_unknown_and_unresolved_cards_preserve_technical_identity():
    unknown = {"kind": "future-operation", "params": {"opaque": 1}}
    unresolved = {
        "kind": "build-field",
        "params": {"subfields": [["a", "literal {name}"]]},
        "authoring_error": "source line needs review",
    }

    unknown_view = task_operation_cards.operation_card_view(
        unknown, position=1, store=None, previews={}
    )
    unresolved_view = task_operation_cards.operation_card_view(
        unresolved, position=2, store=None, previews={}
    )

    assert unknown_view.validation_status == "Needs attention"
    assert unknown_view.kind == "future-operation"
    assert unresolved_view.validation_errors == ("source line needs review",)
```

Also parameterize preview states: no cache or a changed request=`Not previewed`, current=`Current`, the same request with a changed store revision=`Stale`, and a cached error for the current request=`Failed`.

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_operation_cards.py
```

Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement the pure card view**

Use `task_authoring.describe_operation` for Add/Build, `describe_guided_replace` for Guided, and the palette summary for all other known operations. For an unknown operation use `"Unsupported operation; technical values are preserved."`.

Derive concise targets only from existing parameters:

```python
if tag and subfield:
    target = "{0} ${1}".format(tag, subfield)
elif tag:
    target = tag
elif params.get("src_tag") and params.get("dst_tag"):
    target = "{0} → {1}".format(params["src_tag"], params["dst_tag"])
else:
    target = ""
```

Call `task_authoring.validate_operation(operation, validate_raw_syntax=False)` for lightweight card state; full raw-regex syntax remains enforced by save. Determine guided preview status only through `guided_replace_preview.preview_cache_key`, cached preview `.error`, and `guided_replace_preview.is_current`; catch validation errors and report `Not previewed` rather than crashing.

- [ ] **Step 3: Write failing reorder and confirmation tests**

Pin pure transitions:

```python
def test_reorder_and_remove_copy_the_list_without_rewriting_operations():
    operations = [op("a"), op("b"), op("c")]

    moved = task_operation_cards.move_operation(operations, 1, -1)
    removed = task_operation_cards.remove_operation(operations, 1)

    assert [item["kind"] for item in moved] == ["b", "a", "c"]
    assert [item["kind"] for item in removed] == ["a", "c"]
    assert [item["kind"] for item in operations] == ["a", "b", "c"]
```

Add fake-render tests asserting the card includes text labels for status, an Edit button, accessible move help, and a two-click Remove/Confirm removal sequence keyed by a stable per-render index. First click must not call `on_change`; confirmation must call it once with the copied list.

- [ ] **Step 4: Implement compact rendering**

Use one bordered `st.container` per operation, with a short heading/summary/status row and one action row. Store only the pending remove index under the caller-provided key prefix; do not put UI IDs into operations. Reorder callbacks receive a copied list. Call `on_edit(index)` for Edit and `on_change(new_operations)` for reorder/removal.

Render invalid error text only when concise; otherwise say `Needs attention — edit to review N issues`. Do not render full preview evidence, technical JSON, or operation controls on the card.

- [ ] **Step 5: Verify and commit**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_task_operation_cards.py \
  tests/test_guided_replace_preview.py \
  tests/test_task_authoring.py
```

Expected: PASS; report every skip. Then:

```bash
git add marcedit_web/render/task_operation_cards.py \
  tests/test_task_operation_cards.py
git commit -m "feat: render compact task operation cards"
```

---

### Task 4: Build the transactional Add/Edit operation dialog

**Files:**
- Create: `marcedit_web/render/task_operation_dialog.py`
- Create: `tests/test_task_operation_dialog.py`

**Interfaces:**
- Produces: `OperationDialogState(mode, source_index, selected_kind, opening_value, working_copy, nonce, discard_pending)`.
- Produces: `new_add_state(nonce: int) -> OperationDialogState`.
- Produces: `new_edit_state(operation, *, index: int, nonce: int) -> OperationDialogState` using deep copies.
- Produces: `select_add_kind(state, kind: str) -> OperationDialogState` with current default parameters.
- Produces: `keep_in_task(operations, state) -> list[dict]` with deep-copied insert/replace behavior.
- Produces: `cancel_result(state) -> str`, exactly `"close"` or `"confirm"`.
- Produces: `dialog_contract_error(dialog_callable=None) -> Optional[str]`;
  `None` resolves the current `st.dialog` at call time.
- Produces: `rerun_fragment_or_app() -> None`.
- Produces: `render_active_dialog(state, *, operations, is_admin, store, previews, on_keep, on_close) -> None`.

- [ ] **Step 1: Write failing pure draft-transition tests**

Create `tests/test_task_operation_dialog.py`:

```python
def test_edit_isolated_until_keep_and_cancel_preserves_original():
    original = {
        "kind": "delete-tag",
        "params": {"tag": "001"},
    }
    operations = [original]
    state = task_operation_dialog.new_edit_state(
        original, index=0, nonce=7
    )
    state.working_copy["params"]["tag"] = "003"

    assert operations == [original]
    assert task_operation_dialog.cancel_result(state) == "confirm"
    assert task_operation_dialog.keep_in_task(operations, state) == [{
        "kind": "delete-tag",
        "params": {"tag": "003"},
    }]
    assert operations == [original]


def test_clean_cancel_closes_without_confirmation():
    operation = {"kind": "delete-tag", "params": {"tag": "001"}}
    state = task_operation_dialog.new_edit_state(
        operation, index=0, nonce=1
    )

    assert task_operation_dialog.cancel_result(state) == "close"


def test_add_kind_uses_existing_defaults_and_incomplete_draft_can_be_kept():
    state = task_operation_dialog.select_add_kind(
        task_operation_dialog.new_add_state(3),
        "guided-find-replace",
    )

    kept = task_operation_dialog.keep_in_task([], state)

    assert kept[0]["kind"] == "guided-find-replace"
    assert kept[0]["params"]["replacement_mode"] == "matched_text"
    assert task_authoring.validate_operation(kept[0])
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_operation_dialog.py -k 'isolated or cancel or add_kind'
```

Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement state and default creation**

Use a normal Python 3.9 dataclass (no `slots=True`). `new_edit_state` deep-copies both `opening_value` and `working_copy`. `select_add_kind` gets defaults from the same palette/default logic currently in `tasks._default_params_for`; move that logic into `task_operation_dialog.default_params_for(kind)` and leave a delegating `_default_params_for` wrapper in `tasks.py` until Task 5 updates callers and characterization tests.

`keep_in_task` raises `ValueError` if Add has no selected operation or Edit has an invalid source index. It does not validate the draft; save owns the validation gate. It removes UI-only state by returning only a deep copy of `working_copy` in the established `{"kind", "params", optional provenance/error keys}` shape.

- [ ] **Step 3: Write failing Streamlit contract and fallback tests**

Add:

```python
def test_dialog_contract_checks_capability_not_version_string():
    def supported(title, *, width="small", dismissible=True):
        return title, width, dismissible

    def unsupported(title, *, width="small"):
        return title, width

    assert task_operation_dialog.dialog_contract_error(supported) is None
    assert "dismissible" in task_operation_dialog.dialog_contract_error(
        unsupported
    )


def test_fragment_rerun_falls_back_to_app_scope(monkeypatch):
    calls = []

    def rerun(*, scope="app"):
        calls.append(scope)
        if scope == "fragment":
            raise StreamlitAPIException("not in fragment context")

    monkeypatch.setattr(task_operation_dialog.st, "rerun", rerun)

    task_operation_dialog.rerun_fragment_or_app()

    assert calls == ["fragment", "app"]
```

Also test that a successful fragment call records only `fragment` and that non-`StreamlitAPIException` errors are not swallowed.

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_operation_dialog.py -k 'contract or rerun'
```

Expected: FAIL because the functions do not exist.

- [ ] **Step 4: Implement capability check and safe rerun**

Implement exactly:

```python
def dialog_contract_error(dialog_callable=None) -> Optional[str]:
    candidate = dialog_callable or st.dialog
    if "dismissible" not in inspect.signature(candidate).parameters:
        return (
            "Task operation dialogs require Streamlit's non-dismissible "
            "dialog contract (streamlit>=1.50,<2)."
        )
    return None


def rerun_fragment_or_app() -> None:
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()
```

Do not catch `Exception`. If `dialog_contract_error()` returns text, the coordinator renders `st.error` and does not call a dialog wrapper.

- [ ] **Step 5: Write failing tab and one-dialog tests**

Use a fake Streamlit object that records the dynamic dialog arguments, tab labels, widgets, and buttons. Pin:

```python
assert dialog_calls == [{
    "title": "Edit — Guided find and replace",
    "width": "large",
    "dismissible": False,
}]
assert tabs == ["Set up", "Preview", "Technical details", "Reference"]
assert wrapper_invocations == 1
```

For `delete-tag`, assert tabs are exactly `Set up`, `Reference`. For Add before selection, assert the alphabetical selector is the first recorded widget and no operation controls render. For an unknown or unresolved operation, assert its untouched dict is visible in Technical details and renderer failure does not escape the dialog boundary.

- [ ] **Step 6: Implement the tab shell and existing renderer delegation**

Build the dialog title from mode plus selected palette label; before Add selection use `Add operation`. Create and invoke exactly one wrapper:

```python
wrapper = st.dialog(
    title,
    width="large",
    dismissible=False,
)(render_function)
wrapper()
```

In Set up:

- Add selector options are sorted by displayed label and exclude `custom` for non-admins.
- Add/Build/Guided call existing `render/task_authoring.py` controls with `rerun=rerun_fragment_or_app`.
- Other known kinds use the existing generic palette input behavior moved from `_render_param_input` into `task_operation_dialog.render_param_input`.
- Non-admin custom operations remain read-only exactly as today.
- Unknown/unresolved operations show their preserved technical form and actionable error; they are never coerced.

In Preview:

- Add/Build call `render_operation_explanation` with the first preview record.
- Guided calls `render_guided_replace_preview` and updates its plain summary with `guided_replace_previewed_discard_count`.
- No other operation receives an invented preview.

Technical details appear for Add, Build, Guided, custom, unknown, and unresolved operations. Reference calls only `task_operation_reference.render_reference_entry`; it never calls `open_reference_dialog`.

Wrap only operation-specific rendering/preview in the bounded error boundary:

```python
try:
    render_selected_operation(...)
except (OSError, RuntimeError, TypeError, ValueError) as exc:
    st.error("This operation could not be displayed: {0}".format(exc))
```

Do not catch Streamlit control-flow exceptions or `BaseException`. Preserve `state.working_copy` after an error.

- [ ] **Step 7: Implement Keep and dirty-Cancel interactions**

Keep calls `on_keep(keep_in_task(operations, state))` and then an app rerun. Cancel uses `cancel_result`; a dirty draft first sets `discard_pending=True` and renders **Discard changes** / **Keep editing**. Confirmed discard calls `on_close()` and app rerun. The non-dismissible dialog has no implicit close path.

Every modal opening key prefix includes `state.nonce`, for example `task_operation_dialog_7_setup`. Changing the card index never supplies widget identity.

- [ ] **Step 8: Pin cancellation preview identity**

Add a test with an original guided operation and current cached preview, edit the modal draft to a different replacement, cache a preview for that request, then cancel. Assert:

```python
restored = operations[0]
view = task_operation_cards.operation_card_view(
    restored,
    position=1,
    store=store,
    previews=previews,
)
assert view.preview_status == "Current"
assert guided_replace_preview.preview_cache_key(draft) in previews
assert guided_replace_preview.preview_cache_key(restored) != (
    guided_replace_preview.preview_cache_key(draft)
)
```

This test proves discarded evidence may remain cached but cannot impersonate the restored request.

- [ ] **Step 9: Verify and commit**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_task_operation_dialog.py \
  tests/test_task_operation_reference.py \
  tests/test_task_operation_cards.py \
  tests/test_task_authoring_render.py
```

Expected: PASS; report every skip. Then:

```bash
git add marcedit_web/render/task_operation_dialog.py \
  tests/test_task_operation_dialog.py
git commit -m "feat: add transactional task operation dialog"
```

---

### Task 5: Integrate cards and one active dialog into the Tasks editor

**Files:**
- Modify: `marcedit_web/render/tasks.py`
- Modify: `tests/test_tasks_workspace_modes.py`
- Modify: `tests/test_tasks_export.py`

**Interfaces:**
- Consumes: `task_operation_cards.render_operation_cards`.
- Consumes: `task_operation_dialog.new_add_state`, `new_edit_state`, `render_active_dialog`.
- Consumes: `task_operation_reference.open_reference_dialog`.
- Produces session keys: `K_OPERATION_DIALOG_STATE`, `K_OPERATION_DIALOG_NONCE`, and `K_OPERATION_REFERENCE_REQUESTED`, all reset when the task editor opens/closes.
- Contract: `_render_form_editor()` invokes zero or one dialog wrapper per script run.

- [ ] **Step 1: Replace inline-editor characterization with failing compact-shell tests**

Update `tests/test_tasks_workspace_modes.py`. Remove assertions that all operation controls render inline and replace them with delegation assertions:

```python
def test_form_editor_renders_cards_and_main_actions_without_inline_controls(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operations = [valid_add(), valid_guided()]
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = operations
    calls = []

    monkeypatch.setattr(
        tasks_render.task_operation_cards,
        "render_operation_cards",
        lambda ops, **kwargs: calls.append(("cards", list(ops))),
    )
    monkeypatch.setattr(
        tasks_render.task_operation_dialog,
        "render_active_dialog",
        lambda *args, **kwargs: calls.append(("dialog", None)),
    )
    monkeypatch.setattr(
        tasks_render.task_authoring_render,
        "render_add_field_params",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("controls must not render inline")
        ),
    )

    tasks_render._render_form_editor()

    assert calls == [("cards", operations)]
    assert "+ Add operation" in fake_st.button_labels
    assert "Browse operation reference" in fake_st.button_labels
```

Add tests for Add opening, Edit opening, reorder/removal update, and reference opening. Assert that when operation-dialog state is active, the standalone reference wrapper is not called even if stale reference-request state exists.

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_tasks_workspace_modes.py -k 'form_editor or operation_dialog or operation_reference'
```

Expected: FAIL because `_render_form_editor` still renders full inline controls and the new modules are not integrated.

- [ ] **Step 2: Add modal state lifecycle callbacks**

In `render/tasks.py`, add the three session keys beside the other editor keys. Add small callbacks:

```python
def _next_operation_dialog_nonce() -> int:
    nonce = int(st.session_state.get(K_OPERATION_DIALOG_NONCE, 0)) + 1
    st.session_state[K_OPERATION_DIALOG_NONCE] = nonce
    return nonce


def _open_add_operation_dialog() -> None:
    st.session_state[K_OPERATION_DIALOG_STATE] = (
        task_operation_dialog.new_add_state(
            _next_operation_dialog_nonce()
        )
    )


def _close_operation_dialog() -> None:
    st.session_state[K_OPERATION_DIALOG_STATE] = None
```

Edit uses `new_edit_state(ops[index], index=index, nonce=...)`. Keep replaces `K_EDITOR_OPS` with the copied list supplied by the dialog then clears dialog state. Reorder/removal replaces `K_EDITOR_OPS` with the copied list supplied by cards. Do not mutate an operation in a card callback.

Reset dialog/reference state in `_open_editor_for_new`, `_open_editor_for_existing_row`, successful save, and `_cancel_callback` so one task never inherits another task's modal state.

- [ ] **Step 3: Replace `_render_form_editor` with the compact coordinator**

The form editor performs only:

1. existing non-admin custom warning;
2. card rendering;
3. **+ Add operation** and **Browse operation reference** buttons;
4. a capability error if `dialog_contract_error()` is nonempty;
5. exactly one active dialog call.

If operation-dialog state exists, ignore/clear the reference request and invoke only `render_active_dialog`. Otherwise, a reference button click invokes only `open_reference_dialog`. The first-record lookup moves into the operation dialog's Preview tab and must not happen while only the compact list is visible.

Remove the inline operation dropdown and Operation reference expander. Preserve the existing task metadata, visibility, Save task, Cancel, and code editor outside `_render_form_editor`.

- [ ] **Step 4: Add failing save/submission integration tests**

Add to `tests/test_tasks_workspace_modes.py`:

```python
def test_incomplete_kept_card_blocks_task_save_with_ordinal(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [{"kind": "delete-tag", "params": {"tag": ""}}],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "Operation 1: Tag is required" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]
```

In `tests/test_tasks_export.py`, add a queued/submission test using a saved `# OP:` marker with an empty required tag and assert no `TaskSpec` is appended/submitted and the ordinal issue is shown. Add a valid marker control proving the existing queue path is unchanged.

- [ ] **Step 5: Preserve code mode and serialization contracts**

Run the existing tests that pin code-mode saves, marker round-trip, compiler output, import behavior, and AI exclusions. Fix only integration regressions caused by TASK-186; do not change expected body/imports or AI schema.

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_tasks_workspace_modes.py \
  tests/test_tasks_export.py \
  tests/test_task_builder.py \
  tests/test_ai_task_draft.py \
  tests/test_gemini_task_draft.py \
  tests/test_note_task_draft.py \
  tests/test_marcedit_import.py
```

Expected: PASS; report every skip.

- [ ] **Step 6: Commit the integrated editor**

```bash
git add marcedit_web/render/tasks.py \
  tests/test_tasks_workspace_modes.py tests/test_tasks_export.py
git commit -m "feat: integrate compact modal task authoring"
```

---

### Task 6: Prove all-operation coverage and failure containment

**Files:**
- Modify: `tests/test_task_operation_dialog.py`
- Modify: `tests/test_task_operation_cards.py`
- Modify: `tests/test_tasks_workspace_modes.py`

**Interfaces:**
- Contract: every entry in `task_builder.OPERATIONS_PALETTE` has a modal Add path for admins; non-admins exclude only `custom` from Add but can view a persisted custom operation read-only.
- Contract: renderer/preview exceptions are bounded in the operation dialog and preserve the draft.

- [ ] **Step 1: Write the palette completeness test**

Parameterize over the real palette rather than duplicating a kind list:

```python
@pytest.mark.parametrize(
    "kind",
    [entry["kind"] for entry in task_builder.OPERATIONS_PALETTE],
)
def test_every_palette_kind_enters_the_shared_admin_dialog(kind):
    state = task_operation_dialog.select_add_kind(
        task_operation_dialog.new_add_state(1), kind
    )

    assert state.selected_kind == kind
    assert state.working_copy["kind"] == kind
    assert isinstance(state.working_copy["params"], dict)
```

Add a non-admin test proving only `custom` is absent from selectable kinds and a persisted custom operation's code remains unchanged after open/cancel.

- [ ] **Step 2: Pin lossless save/reopen and reorder**

Build a synthetic form task containing one Add, Build, Guided, generic delete, custom, and unresolved operation. Exercise modal keep/reorder transitions, call the existing compiler/save serialization, parse the `# OP:` markers, and assert every operation dict and order match except the one deliberate edit. The unresolved operation is expected to block save; repeat after removing it to prove valid round-trip.

Use synthetic strings only; no institutional tasks or vendor records.

- [ ] **Step 3: Pin failure containment**

Monkeypatch each delegated renderer and guided preview in turn to raise one allowed bounded exception. Assert `render_active_dialog` returns, calls `st.error`, leaves `state.working_copy` equal to its pre-render value, and never invokes `on_keep` or `on_close`. Separately assert a Streamlit control-flow exception is not swallowed.

- [ ] **Step 4: Run the complete focused UI and task suite**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_task_operation_dialog.py \
  tests/test_task_operation_cards.py \
  tests/test_task_operation_reference.py \
  tests/test_task_authoring.py \
  tests/test_task_authoring_render.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_tasks_export.py \
  tests/test_task_builder.py \
  tests/test_guided_replace.py \
  tests/test_guided_replace_preview.py \
  tests/test_ai_task_draft.py \
  tests/test_gemini_task_draft.py \
  tests/test_note_task_draft.py \
  tests/test_marcedit_import.py
```

Expected: PASS; list every skip and reason. Commit:

```bash
git add tests/test_task_operation_dialog.py \
  tests/test_task_operation_cards.py \
  tests/test_tasks_workspace_modes.py
git commit -m "test: cover modal authoring across task operations"
```

---

### Task 7: Document, browser-test, verify, and review TASK-186

**Files:**
- Modify: `docs/task-authoring-syntax.md`
- Create: `docs/superpowers/evidence/task-186-compact-modal-task-authoring-browser-smoke.md`
- Modify: `.tickets/TASK-186-compact-modal-task-authoring.md`
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`

**Interfaces:**
- Produces: cataloger-facing workflow documentation and reproducible synthetic browser evidence.
- Produces: completed ticket traceability only after verification and independent review.

- [ ] **Step 1: Update the authoring guide**

Add a short “Working with operation cards” section that states:

- the main page shows ordered summaries rather than full forms;
- **+ Add operation** and **Edit** open a Workspace with setup beside preview when preview applies, plus Technical details and Reference tabs when relevant;
- **Keep in task** retains a draft but does not guarantee it can be saved or run;
- **Needs attention** identifies the numbered operation that must be fixed;
- Cancel does not change the task and confirms before discarding edits;
- preview status is request/source-aware and reordering does not change preview meaning; and
- the standalone alphabetical reference is read-only.

Keep all MARC syntax and technical examples visible; the modal workflow supplements rather than hides them.

- [ ] **Step 2: Rebuild and run dependency preflight**

Run:

```bash
docker compose build marcedit-web
docker compose run --rm marcedit-web python -c \
  'import inspect, streamlit as st; assert "dismissible" in inspect.signature(st.dialog).parameters; print(st.__version__)'
```

Expected: image builds and prints a Streamlit version in `1.50.x` or later but below `2`; signature assertion passes.

- [ ] **Step 3: Run complete automated verification**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra
```

Expected: the full suite passes; report exact passed/failed/skipped totals and every skip reason.

Run the native compiler freshness guard:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition
git diff --exit-code main -- \
  marcedit_web/schemas/native-task-compiler-contract-v1.json
```

Expected: test passes and manifest diff is empty.

Run repository checks:

```bash
git diff --check main...
git status --short
git diff --name-only main... | sort
```

Expected: no whitespace errors; only TASK-186-traceable files appear; `MarcEdit Tasks/`, `data/`, credentials, and local screenshots are absent.

- [ ] **Step 4: Perform Docker browser acceptance with synthetic data**

Start the rebuilt app using the repository's documented local-auth bypass only; do not change production authentication settings. In a clean browser session:

1. Open Tasks → Build & import → New task in form mode.
2. Confirm the main editor has no operation selector or expanded operation controls.
3. Add at least six operations, including Add field, Build field from template, Guided find and replace, Delete tag, Sort fields by tag, and one deliberately incomplete operation.
4. Confirm the selector is alphabetical and each kept operation becomes one short ordered card.
5. Confirm Guided shows setup and preview together in an approximately 45/55 Workspace, while simple operations use the full Workspace width and omit empty preview/Technical surfaces.
6. Preview a synthetic 035 replacement and confirm its card says Current without showing full MARC.
7. Reorder the Guided card and confirm Current remains.
8. Edit its replacement, preview the draft, Cancel, confirm discard, and verify the restored card shows the original Current status—not the discarded draft's preview.
9. Confirm dirty Cancel prompts, clean Cancel closes directly, and Remove requires confirmation.
10. Keep the incomplete operation and confirm its card says Needs attention; Save task must identify its ordinal and refuse.
11. Correct it, save, reopen, and verify order/meaning survive.
12. Open the standalone reference from the main page, search by label and summary, and confirm alphabetical results.
13. Open an operation dialog and confirm Reference content appears inside its tab without a nested dialog.
14. As a non-admin, verify custom code cannot be newly selected and persisted custom code remains read-only; as an admin, verify code mode remains unchanged.

Record browser, container image/commit, synthetic setup, observed results, and any skipped step with reason in `docs/superpowers/evidence/task-186-compact-modal-task-authoring-browser-smoke.md`. Do not include real MARC data or identities.

- [ ] **Step 5: Request independent review and resolve findings**

Use `superpowers:requesting-code-review` against the full TASK-186 diff. Require the reviewer to check:

- only one dialog can open per script run;
- dynamic title and non-dismissible contract are correct;
- all eight existing renderer reruns use the injected callable;
- fragment rejection falls back to app scope;
- draft/cancel/preview cache isolation is real;
- every palette kind remains accessible under the correct role;
- invalid/unresolved operations block save and submission without data loss;
- code, compiler, AI, import, sharing, and worker behavior are unchanged; and
- no Critical or Important finding remains.

If review causes changes, add a focused failing test before each behavioral correction, rerun the focused suite, then rerun Step 3's complete verification.

- [ ] **Step 6: Complete tickets and commit documentation**

Update TASK-186 with exact test totals, skips, browser evidence, commit IDs, and review outcome; set `Status: Completed` only now. Update TASK-174 only to mark the TASK-186 child complete—do not advance unrelated children.

```bash
git add docs/task-authoring-syntax.md \
  docs/superpowers/evidence/task-186-compact-modal-task-authoring-browser-smoke.md \
  .tickets/TASK-186-compact-modal-task-authoring.md \
  .tickets/TASK-174-smith-metadata-studio-open-task-migration.md
git commit -m "docs: complete compact modal task authoring"
```

- [ ] **Step 7: Final clean verification**

Run from the committed tree:

```bash
docker compose run --rm marcedit-web pytest -ra
git diff --check main...
git status --short
```

Expected: complete suite passes with exact skip reporting, no whitespace errors, and the worktree is clean.

---

### Task 8: Combine setup and preview in one split Workspace

**Files:**
- Modify: `marcedit_web/render/task_operation_dialog.py`
- Modify: `tests/test_task_operation_dialog.py`
- Modify: `docs/task-authoring-syntax.md`
- Modify: `docs/superpowers/evidence/task-186-compact-modal-task-authoring-browser-smoke.md`

**Interfaces:**
- Preserves: `_preview_required(operation, entry) -> bool` as the single decision for whether a preview surface exists.
- Preserves: `_render_with_draft_restore(state, render) -> None` independently around setup and preview so a bounded failure in one side does not silently mutate the modal draft.
- Changes: `render_active_dialog(...)` renders tab labels `Workspace`, optional `Technical details`, and `Reference`; it no longer emits separate `Set up` or `Preview` tabs.
- Contract: preview-capable operations call `st.columns([5, 6])` once inside Workspace and render setup on the left and preview on the right. Other operations and the initial Add selector do not create preview columns.

- [ ] **Step 1: Write failing split-Workspace tests**

Extend `FakeStreamlit` in `tests/test_task_operation_dialog.py` to record column specifications while returning context-manager objects:

```python
def __init__(self, *, selections=None, pressed=()):
    # Existing fields remain unchanged.
    self.column_calls = []

def columns(self, spec):
    self.column_calls.append(spec)
    count = spec if isinstance(spec, int) else len(spec)
    return [_Context() for _index in range(count)]
```

Rename the existing guided-dialog test and change its assertions to:

```python
assert fake.tab_calls == [[
    "Workspace", "Technical details", "Reference"
]]
assert fake.column_calls == [[5, 6]]
assert controls
assert previews
```

Change the simple-operation assertion to:

```python
assert fake.tab_calls == [["Workspace", "Reference"]]
assert fake.column_calls == []
```

In the initial Add-selector test, also assert `fake.column_calls == []`. Keep
the guided test's `store=None`: the recorded preview delegate call proves the
right-hand surface remains present even before a file is loaded.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_operation_dialog.py \
  -k 'guided_edit or delete_tag or add_starts'
```

Expected: FAIL because the current dialog emits separate `Set up` and
`Preview` tabs and never calls `st.columns([5, 6])` for the primary workflow.

- [ ] **Step 3: Implement the minimum split Workspace**

In `render_active_dialog`, build tab labels as follows:

```python
tab_labels = ["Workspace"]
if current_operation is not None and _technical_form_required(
    current_operation, current_entry
):
    tab_labels.append("Technical details")
tab_labels.append("Reference")
tabs = dict(zip(tab_labels, st.tabs(tab_labels)))
```

Inside `tabs["Workspace"]`, keep the current full-width Add selector. When a
working copy exists and `_preview_required(...)` is true, render:

```python
setup_column, preview_column = st.columns([5, 6])
with setup_column:
    _render_with_draft_restore(
        state,
        lambda: render_selected_operation(state, is_admin=is_admin),
    )
with preview_column:
    _render_with_draft_restore(
        state,
        lambda: _render_preview(
            state, store=store, previews=previews
        ),
    )
```

When preview is unsupported, render only `render_selected_operation` at full
Workspace width. Remove the separate Preview-tab branch. Do not change preview
caching, validation, renderer rerun injection, draft copying, or Keep/Cancel.

- [ ] **Step 4: Update cataloger documentation and browser acceptance wording**

In `docs/task-authoring-syntax.md`, replace the separate Set up/Preview tab
description with:

```markdown
The **Workspace** keeps setup controls beside preview results when an operation
supports preview, so you can adjust settings and inspect the MARC result
without changing tabs. Operations without preview use the full Workspace.
**Technical details** and **Reference** remain separate when relevant.
```

In the browser evidence matrix, replace the old four-tab check with an
unperformed check for the split Workspace. Keep its result `SKIP`; this task
does not convert automated layout tests into browser evidence.

- [ ] **Step 5: Run focused and complete verification**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_task_operation_dialog.py \
  tests/test_task_authoring_render.py \
  tests/test_task_operation_cards.py \
  tests/test_tasks_workspace_modes.py
docker compose run --rm -v "$PWD:/app:ro" marcedit-web pytest -ra
docker compose run --rm marcedit-web pytest -q \
  tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition
git diff --exit-code -- \
  marcedit_web/schemas/native-task-compiler-contract-v1.json
git diff --check
```

Expected: all focused tests pass with no silent skips; the complete suite has
zero failures and reports every skip; the native compiler contract passes and
its manifest remains unchanged.

- [ ] **Step 6: Request review and commit the amendment**

Request focused review of the layout diff. Require confirmation that setup and
preview render in the same Workspace, no-preview operations remain full-width,
the Add selector remains full-width, failure containment remains independent,
and no storage/preview/compiler semantics changed. Resolve every Critical or
Important finding with a failing regression test.

```bash
git add marcedit_web/render/task_operation_dialog.py \
  tests/test_task_operation_dialog.py \
  docs/task-authoring-syntax.md \
  docs/superpowers/evidence/task-186-compact-modal-task-authoring-browser-smoke.md
git commit -m "feat: show task setup beside preview"
```

Keep TASK-186 `In-Progress` and TASK-174 unchanged until the real browser
acceptance matrix passes.

---

## Success-Criteria Traceability

- Compact ordered list and reduced scrolling: Tasks 3, 5, and 7 browser acceptance.
- Alphabetical Add selector: Tasks 2, 4, and 5.
- Isolated Edit, Keep, clean Cancel, dirty confirmation: Task 4.
- Summary, target, validation, preview, and actions on cards: Task 3.
- Split setup/preview Workspace and secondary-tab omission: Tasks 4 and 8.
- Invalid/unresolved visible but save/submission blocked: Tasks 1, 3, and 5.
- Reorder/save/reopen/import/cancel identity: Tasks 3, 4, 6, and 7.
- Streamlit `>=1.50,<2` and signature preflight: Tasks 1, 4, and 7.
- Renderer parity and fragment fallback: Tasks 1 and 4.
- Discarded draft cannot replace original preview status: Tasks 3 and 4.
- Docker automation and cataloger browser acceptance: Tasks 6 and 7.
- Independent review with no unresolved Critical/Important findings: Task 7.
