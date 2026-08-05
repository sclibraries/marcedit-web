# TASK-193 Task Workspace Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the crowded Tasks workspace switcher with URL-synchronized Run, Library, Create, and Import workflows while preserving drafts, filter state, browser history, and explicit modal exits.

**Architecture:** A new Streamlit-independent navigation module parses and merges only Tasks-owned query parameters. `render/tasks.py` remains the workflow coordinator: it validates URL targets through existing authorized task-library APIs, renders stateful segmented controls, stages Library filters, and keeps drafts in explicit non-widget session state. Existing task storage, execution, import conversion, authorization, and folder services remain unchanged.

**Tech Stack:** Python 3.9, Streamlit 1.50, pytest, SQLite-backed task-library services, Docker Compose.

**Ticket:** [TASK-193](../../../.tickets/TASK-193-task-library-folders-search.md)

**Design:** [TASK-193 task workspace navigation and dialog usability](../specs/2026-08-05-task-193-task-workspace-navigation-design.md)

## Global Constraints

- Keep `.tickets/TASK-193-task-library-folders-search.md` `In-Progress` until all automated tests, authenticated browser acceptance, and code review pass.
- Before implementation, checkpoint the existing reviewed TASK-192/193/194 working-tree changes or create the execution worktree from a commit containing them. No navigation commit may accidentally absorb unrelated dirty files.
- Use Streamlit 1.50 and Python 3.9; do not upgrade dependencies.
- Use `st.segmented_control`, because Streamlit 1.50 `st.tabs` cannot expose controlled selected-tab state.
- URL writes replace only Tasks-owned keys and preserve `job_file`, `start`, repeated unknown keys, and every other non-Tasks query parameter.
- Do not put task definitions, imported instruction bodies, MARC data, OAuth data, or unsaved field values in the URL.
- Drafts and dialog working copies must use explicitly managed non-widget session keys so Streamlit widget cleanup cannot discard them.
- Search/filter typing must not write browser history. Apply, Clear, structural navigation, task selection, and dialog changes each make one atomic URL write.
- The URL is authoritative for whether a dialog is open; retained dialog state alone must never reopen it.
- Do not change task execution, compiler, migration, database schema, authorization, systemd, sudoers, OAuth, proxy, or durable-worker behavior.

---

### Task 1: Deterministic Tasks Query Contract

**Files:**
- Create: `marcedit_web/lib/task_workspace_navigation.py`
- Create: `tests/test_task_workspace_navigation.py`

**Interfaces:**
- Consumes: a complete query mapping represented as `Mapping[str, str | Sequence[str]]`.
- Produces: `LibraryFilters`, `WorkspaceLocation`, `parse_tasks_query(raw, *, operation_kinds)`, `canonical_tasks_query(location)`, and `merge_tasks_query(raw, location)`.
- `parse_tasks_query` validates syntax and enums only. Authorized task/folder existence remains a renderer responsibility.

- [ ] **Step 1: Write failing round-trip, rejection, and merge tests**

```python
def test_tasks_query_round_trips_all_supported_values():
    raw = {
        "view": "library", "scope": "shared", "folder": "41",
        "q": "856", "visibility": "shared", "owner": "smith.edu",
        "tag": "856", "subfield": "u", "operation": "delete-tag",
        "validation": "valid", "updated": "7",
    }
    location = parse_tasks_query(raw, operation_kinds={"delete-tag"})
    assert canonical_tasks_query(location) == raw


def test_invalid_values_fall_back_independently():
    location = parse_tasks_query({
        "view": "wrong", "mode": "wrong", "folder": "-2",
        "visibility": "shared", "updated": "yesterday",
    }, operation_kinds={"delete-tag"})
    assert location.view == "run"
    assert location.mode == "saved"
    assert location.folder_id is None
    assert location.filters.visibility == "shared"
    assert location.filters.updated == "any"


def test_merge_preserves_non_tasks_and_repeated_values():
    merged = merge_tasks_query(
        {"job_file": "12", "start": "upload", "external": ["a", "b"],
         "view": "run"},
        WorkspaceLocation(view="library"),
    )
    assert merged == {
        "job_file": "12", "start": "upload", "external": ["a", "b"],
        "view": "library",
    }
```

- [ ] **Step 2: Run the tests and confirm the missing module is the RED failure**

Run: `python -m pytest tests/test_task_workspace_navigation.py -q`

Expected: collection fails with `ModuleNotFoundError: marcedit_web.lib.task_workspace_navigation`.

- [ ] **Step 3: Implement immutable bounded navigation values and serializers**

```python
TASK_QUERY_KEYS = frozenset({
    "view", "mode", "scope", "folder", "q", "visibility", "owner",
    "tag", "subfield", "operation", "validation", "updated", "task",
    "dialog", "dialog_task", "dialog_folder",
})

@dataclass(frozen=True)
class LibraryFilters:
    query: str = ""
    visibility: str = "all"
    owner: str = ""
    tag: str = ""
    subfield: str = ""
    operation: str = "all"
    validation: str = "all"
    updated: str = "any"

@dataclass(frozen=True)
class WorkspaceLocation:
    view: str = "run"
    mode: str = "saved"
    scope: str = "personal"
    folder_id: int | None = None
    filters: LibraryFilters = LibraryFilters()
    task_id: int | None = None
    dialog: str | None = None
    dialog_task_id: int | None = None
    dialog_folder_id: int | None = None

def merge_tasks_query(raw, location: WorkspaceLocation):
    merged = {key: value for key, value in raw.items()
              if key not in TASK_QUERY_KEYS}
    merged.update(canonical_tasks_query(location))
    return merged
```

Implement scalar extraction that accepts Streamlit scalar/list values, positive-integer parsing for IDs, per-field enum fallback, the explicit URL length bounds below, and omission of canonical defaults. Preserve non-Tasks list values without flattening them.

Use explicit URL bounds: 255 characters for `q` and `owner`, three characters for `tag`, one alphanumeric character for `subfield`, and 64 characters for the operation slug. Accept an operation only when it is `all` or belongs to the `operation_kinds` set supplied by the renderer from `OPERATIONS_PALETTE`; this avoids a duplicated operation registry.

- [ ] **Step 4: Add parameterized tests for every supported key and privacy exclusions**

```python
@pytest.mark.parametrize("key", sorted(TASK_QUERY_KEYS))
def test_every_tasks_key_is_owned_and_canonicalized(key):
    assert key in TASK_QUERY_KEYS


def test_navigation_has_no_definition_or_record_fields():
    fields = {field.name for field in dataclasses.fields(WorkspaceLocation)}
    assert fields.isdisjoint({"body", "operations", "source_line", "marc"})
```

- [ ] **Step 5: Run the focused tests**

Run: `python -m pytest tests/test_task_workspace_navigation.py -q`

Expected: all tests pass with zero skips.

- [ ] **Step 6: Commit the navigation contract**

```bash
git add marcedit_web/lib/task_workspace_navigation.py tests/test_task_workspace_navigation.py
git commit -m "feat: define TASK-193 workspace URL contract"
```

---

### Task 2: URL Synchronization and Stateful Workflow Navigation

**Files:**
- Modify: `marcedit_web/render/tasks.py:128-292`
- Modify: `tests/test_tasks_workspace_modes.py:1-230`
- Test: `tests/test_task_workspace_navigation.py`

**Interfaces:**
- Consumes: Task 1's `WorkspaceLocation`, `parse_tasks_query`, and `merge_tasks_query`.
- Produces: `_read_workspace_location()`, `_write_workspace_location(location)`, `_sync_workspace_from_url(location, visible_task_ids, visible_folder_ids)`, and `_select_workspace(view, **changes)`.
- Session keys: `K_WORKSPACE_LOCATION` and `K_WORKSPACE_OWN_WRITE` are non-widget navigation state. Existing `K_EDITOR_*`, `K_MARCEDIT_IMPORT_RESULT`, and `K_MARCEDIT_IMPORT_ADOPTED_ENTRY` values remain the non-widget Create and Import working copies; selector and form widgets use separate keys.

- [ ] **Step 1: Replace old radio expectations with failing four-view routing tests**

```python
@pytest.mark.parametrize(
    ("view", "expected"),
    [("run", "run"), ("library", "library"),
     ("create", "create"), ("import", "import")],
)
def test_render_routes_exactly_one_primary_workspace(monkeypatch, fake_st,
                                                      view, expected):
    calls = []
    fake_st.query_params.from_dict({"view": view})
    monkeypatch.setattr(tasks_render, "_render_saved_tasks", lambda *a: calls.append("run"))
    monkeypatch.setattr(tasks_render, "_render_task_library", lambda **k: calls.append("library"))
    monkeypatch.setattr(tasks_render, "_render_create_workspace", lambda *a: calls.append("create"))
    monkeypatch.setattr(tasks_render, "_render_import_workspace", lambda *a: calls.append("import"))
    tasks_render.render()
    assert calls == [expected]
```

Add a Run test proving `mode=quick` invokes Quick changes and `mode=saved` invokes Saved tasks. Extend the existing fake Streamlit object with `segmented_control` and a query-parameter fake exposing `get_all()` and `from_dict()`.

- [ ] **Step 2: Add the required failing page-reinitialization draft regression**

```python
def test_external_query_reinitialization_preserves_create_and_import_drafts(fake_st):
    operations = [{"kind": "delete-tag", "params": {"tag": "029"}}]
    import_result = {"status": "partial", "uploaded_filename": "partner.task",
                     "imported_task_names": [], "entries": []}
    fake_st.session_state[tasks_render.K_EDITOR_NAME] = "working"
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = copy.deepcopy(operations)
    fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] = copy.deepcopy(import_result)

    # Model Streamlit's cleanup of widgets that disappeared during the
    # query-only page-change rerun. The authoritative non-widget values must
    # remain sufficient to restore both drafts.
    fake_st.session_state.pop(tasks_render.K_EDITOR_NAME_INPUT, None)
    fake_st.session_state.pop(tasks_render.K_EDITOR_DESCRIPTION_INPUT, None)
    fake_st.session_state.pop("tasks_import_uploader", None)

    tasks_render._sync_workspace_from_url(
        WorkspaceLocation(view="library"),
        visible_task_ids=set(), visible_folder_ids=set(),
    )
    tasks_render._sync_workspace_from_url(
        WorkspaceLocation(view="create"),
        visible_task_ids=set(), visible_folder_ids=set(),
    )

    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "working"
    assert fake_st.session_state[tasks_render.K_EDITOR_OPS] == operations
    assert fake_st.session_state[tasks_render.K_MARCEDIT_IMPORT_RESULT] == import_result
```

- [ ] **Step 3: Run the two RED groups**

Run: `python -m pytest tests/test_tasks_workspace_modes.py -k 'routes_exactly_one or reinitialization or run_mode' -q`

Expected: failures because the four-view controls and synchronization helpers do not exist.

- [ ] **Step 4: Implement synchronization and segmented navigation**

Replace `MODE_RUN`, `MODE_QUICK`, `MODE_BUILD`, `_MODES`, and `K_FORCE_MODE` with controlled values:

```python
WORKSPACE_VIEWS = {
    "run": "Run", "library": "Library", "create": "Create", "import": "Import",
}
RUN_MODES = {"saved": "Saved tasks", "quick": "Quick changes"}

def _write_workspace_location(location: WorkspaceLocation) -> None:
    merged = merge_tasks_query(_complete_query_mapping(), location)
    st.session_state[K_WORKSPACE_OWN_WRITE] = canonical_tasks_query(location)
    st.query_params.from_dict(merged)

def _select_workspace(view: str, **changes: object) -> None:
    current = st.session_state[K_WORKSPACE_LOCATION]
    _write_workspace_location(dataclasses.replace(current, view=view, **changes))
    st.rerun()
```

Render `st.segmented_control` with the labels above, translate labels back to stable lowercase URL values, and invoke exactly one existing workflow. Compare the parsed canonical URL to `K_WORKSPACE_OWN_WRITE` before applying external state so the app's own rerun does not loop.

- [ ] **Step 5: Preserve non-Tasks query owners during a real renderer write**

```python
def test_workspace_write_preserves_job_file_start_and_unknown_values(fake_st):
    fake_st.query_params.from_dict({
        "job_file": "22", "start": "jobs", "future": ["x", "y"],
    })
    tasks_render._write_workspace_location(WorkspaceLocation(view="library"))
    assert fake_st.query_params.get_all("future") == ["x", "y"]
    assert fake_st.query_params["job_file"] == "22"
    assert fake_st.query_params["start"] == "jobs"


def test_external_url_cannot_open_inaccessible_task_or_folder(fake_st):
    requested = WorkspaceLocation(
        view="create", task_id=90, scope="shared", folder_id=80,
        dialog="task-move", dialog_task_id=90,
    )
    resolved = tasks_render._sync_workspace_from_url(
        requested, visible_task_ids={12}, visible_folder_ids={21},
    )
    assert resolved.view == "library"
    assert resolved.task_id is None
    assert resolved.folder_id is None
    assert resolved.dialog is None
```

- [ ] **Step 6: Run the routing and navigation tests**

Run: `python -m pytest tests/test_task_workspace_navigation.py tests/test_tasks_workspace_modes.py -k 'workspace or route or draft or mode' -q`

Expected: all selected tests pass with zero skips.

- [ ] **Step 7: Commit workflow navigation**

```bash
git add marcedit_web/render/tasks.py tests/test_tasks_workspace_modes.py tests/test_task_workspace_navigation.py
git commit -m "feat: add URL-synchronized task workflows"
```

---

### Task 3: Separate Library, Create, and Import Workspaces

**Files:**
- Modify: `marcedit_web/render/tasks.py:620-936,1292-1700,2110-2335`
- Modify: `tests/test_tasks_workspace_modes.py`

**Interfaces:**
- Consumes: Task 2's `_select_workspace` and explicit draft session keys.
- Produces: `_render_saved_tasks`, `_render_create_workspace`, `_render_import_workspace`, `_adopt_import_into_create`, and `_discard_create_draft`.
- Existing `_render_task_library`, `_render_editor`, `_do_marcedit_import`, and `_render_marcedit_import_result` retain business semantics.

- [ ] **Step 1: Write failing workflow-transition tests**

```python
def test_library_edit_opens_create_with_stable_task_id(monkeypatch, fake_st):
    row = {"id": 71, "name": "fix-856", "owner_email": "a@smith.edu",
           "visibility": "private", "description": "", "body": "pass"}
    tasks_render._open_editor_for_existing_row(row, is_admin=False)
    location = fake_st.session_state[tasks_render.K_WORKSPACE_LOCATION]
    assert location.view == "create"
    assert location.task_id == 71


def test_import_adoption_opens_unsaved_create_draft(fake_st):
    draft = {"name": "partner-import", "operations": [{"kind": "delete-tag"}]}
    tasks_render._adopt_import_into_create(draft)
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == "partner-import"
    assert fake_st.session_state[tasks_render.K_EDITOR_OPS] == draft["operations"]
    assert fake_st.session_state[tasks_render.K_WORKSPACE_LOCATION].view == "create"


def test_discard_is_the_only_routine_create_draft_cleanup(fake_st):
    fake_st.session_state[tasks_render.K_EDITOR_OPEN] = True
    fake_st.session_state[tasks_render.K_EDITOR_NAME] = "working"
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = [{"kind": "delete-tag"}]
    tasks_render._discard_create_draft()
    assert fake_st.session_state[tasks_render.K_EDITOR_OPEN] is False
    assert fake_st.session_state[tasks_render.K_EDITOR_NAME] == ""
    assert fake_st.session_state[tasks_render.K_EDITOR_OPS] == []
```

- [ ] **Step 2: Run the transition tests and confirm RED**

Run: `python -m pytest tests/test_tasks_workspace_modes.py -k 'opens_create or adoption or discard' -q`

Expected: failures for missing helpers or the old `Build & import` force mode.

- [ ] **Step 3: Split the existing Build & import renderer without changing services**

Move only presentation orchestration:

```python
def _render_create_workspace(tasks_dir: Path, is_admin: bool) -> None:
    if not st.session_state.get(K_EDITOR_OPEN):
        if st.button("Create a new task", type="primary", key="tasks_new"):
            _open_editor_for_new()
            st.rerun()
        return
    _render_editor(tasks_dir, is_admin)

def _render_import_workspace(tasks_dir: Path) -> None:
    uploaded = st.file_uploader(
        "Import an external task", type=["txt", "task"],
        key="tasks_import_uploader",
    )
    if uploaded is not None and st.button("Review import", type="primary"):
        _do_marcedit_import(uploaded, tasks_dir)
    if st.session_state.get(K_MARCEDIT_IMPORT_RESULT) is not None:
        _render_marcedit_import_result()
```

Keep Create working data in the existing non-widget `K_EDITOR_NAME`, `K_EDITOR_DESCRIPTION`, `K_EDITOR_BODY`, `K_EDITOR_OPS`, provenance, and ownership keys. Keep Import working data in `K_MARCEDIT_IMPORT_RESULT` and `K_MARCEDIT_IMPORT_ADOPTED_ENTRY`. Continue copying widget return values into those authoritative keys as the existing editor does; do not duplicate import parsing or editor save logic.

- [ ] **Step 4: Update all existing editor entry points**

Change Library Edit, New task, AI-draft adoption, migration-choice adoption, and full import adoption to select `view=create`. Saving returns to Library with the saved task selected; Cancel/Discard removes the draft explicitly. Navigating to Run, Library, or Import alone does not clear it.

- [ ] **Step 5: Run workflow and importer regressions**

Run: `python -m pytest tests/test_tasks_workspace_modes.py tests/test_marcedit_import.py tests/test_external_task_migration.py -q`

Expected: all tests pass; any skips are reported with their exact reason.

- [ ] **Step 6: Commit the separated workspaces**

```bash
git add marcedit_web/render/tasks.py tests/test_tasks_workspace_modes.py
git commit -m "feat: separate task library create and import workflows"
```

---

### Task 4: Applied Library Filters and Discoverable Folder Creation

**Files:**
- Modify: `marcedit_web/render/tasks.py:1027-1530`
- Modify: `tests/test_tasks_workspace_modes.py`
- Test: `tests/test_task_workspace_navigation.py`

**Interfaces:**
- Consumes: `WorkspaceLocation.filters`, `_write_workspace_location`, and existing `task_library` / `task_library_search` APIs.
- Produces: `K_LIBRARY_FILTER_DRAFT`, `_apply_library_filters`, `_clear_library_filters`, and `_open_create_folder(scope: str, parent_id: int | None)`.
- Search results always consume applied URL filters, never uncommitted widget values.

- [ ] **Step 1: Write failing history-write and staged-filter tests**

```python
def test_filter_typing_does_not_write_query_params(fake_st):
    fake_st.session_state[tasks_render.K_LIBRARY_FILTER_DRAFT] = {
        "query": "856", "visibility": "all", "owner": "", "tag": "",
        "subfield": "", "operation": "all", "validation": "all",
        "updated": "any",
    }
    tasks_render._render_library_filters()
    assert fake_st.query_params.write_count == 0


def test_apply_filters_writes_once_and_updates_applied_location(fake_st):
    fake_st.session_state[tasks_render.K_LIBRARY_FILTER_DRAFT] = {
        "query": "EBA", "visibility": "shared", "owner": "", "tag": "035",
        "subfield": "a", "operation": "all", "validation": "valid",
        "updated": "30",
    }
    tasks_render._apply_library_filters()
    assert fake_st.query_params.write_count == 1
    assert fake_st.query_params["q"] == "EBA"
    assert fake_st.query_params["tag"] == "035"
```

Also test Clear writes once, dirty state displays `Filters not applied`, and a folder click commits staged filters in the same single URL write.

- [ ] **Step 2: Run staged-filter tests and confirm RED**

Run: `python -m pytest tests/test_tasks_workspace_modes.py -k 'filter_typing or apply_filters or clear_filters or staged' -q`

Expected: failures because filters currently search and rerun directly from widget state.

- [ ] **Step 3: Put Library filters in one form with explicit Apply and Clear**

```python
with st.form("tasks_library_filters"):
    # Render existing search and select controls into K_LIBRARY_FILTER_DRAFT.
    applied = st.form_submit_button("Apply filters", type="primary")
    cleared = st.form_submit_button("Clear filters")
if applied:
    _apply_library_filters()
if cleared:
    _clear_library_filters()
if _library_filters_are_dirty():
    st.caption("Filters not applied")
```

Initialize filter widgets from the parsed URL after external Back/Forward or refresh. Pass only `WorkspaceLocation.filters` into `search_visible_tasks`.

- [ ] **Step 4: Replace ambiguous folder buttons with explicit actions**

Render one `Create new folder` primary button with a plus icon. Its dialog uses written-out Personal/Shared location labels and a compatible parent selector. When a folder is selected, render `Create subfolder here`, preselect its parent, and allow changing to another compatible parent.

```python
if st.button(
    ":material/create_new_folder: Create new folder",
    type="primary", use_container_width=True,
    key="tasks_library_create_folder",
):
    _open_create_folder(parent_id=None)
```

- [ ] **Step 5: Add Personal, Shared, root, and selected-parent tests**

```python
@pytest.mark.parametrize(
    ("scope", "parent_id"),
    [("personal", None), ("shared", None), ("personal", 11), ("shared", 21)],
)
def test_create_folder_dialog_preserves_explicit_location(fake_st, scope, parent_id):
    tasks_render._open_create_folder(scope=scope, parent_id=parent_id)
    draft = fake_st.session_state[tasks_render.K_LIBRARY_DIALOG_DRAFT]
    assert draft["scope"] == scope
    assert draft["parent_id"] == parent_id
```

- [ ] **Step 6: Run Library regressions**

Run: `python -m pytest tests/test_tasks_workspace_modes.py tests/test_task_library.py tests/test_task_library_search.py -q`

Expected: all tests pass; any skips are reported with exact reasons.

- [ ] **Step 7: Commit Library interaction changes**

```bash
git add marcedit_web/render/tasks.py tests/test_tasks_workspace_modes.py tests/test_task_workspace_navigation.py
git commit -m "feat: stage task filters and clarify folder creation"
```

---

### Task 5: Explicit Dialog Exit and Browser-History Precedence

**Files:**
- Modify: `marcedit_web/render/tasks.py:1061-1291`
- Modify: `tests/test_tasks_workspace_modes.py`
- Modify: `tests/test_task_operation_dialog.py`

**Interfaces:**
- Consumes: URL dialog fields from `WorkspaceLocation` and existing authorized task/folder lookup APIs.
- Produces: `K_LIBRARY_DIALOG_DRAFT`, `_close_library_dialog(discard: bool)`, and `_restore_dialog_from_location(location, visible_task_ids, visible_folder_ids)`.
- `_close_library_dialog(discard=True)` deletes the working copy; an external Back closes while retaining it.

- [ ] **Step 1: Write failing modal-exit matrix tests**

```python
@pytest.mark.parametrize("mode", [
    "folder-create", "folder-rename", "folder-move", "folder-delete",
    "task-move", "task-share", "task-unshare",
])
def test_every_library_dialog_has_cancel(mode, monkeypatch, fake_st):
    fake_st.session_state[tasks_render.K_LIBRARY_DIALOG] = mode
    tasks_render._render_library_dialog()
    assert "Cancel" in fake_st.button_labels


def test_stale_folder_dialog_has_close_and_no_mutation(fake_st, monkeypatch):
    fake_st.session_state[tasks_render.K_LIBRARY_DIALOG] = "folder-rename"
    fake_st.session_state[tasks_render.K_LIBRARY_DIALOG_FOLDER] = 999
    monkeypatch.setattr(tasks_render.task_library, "list_folder_tree", lambda actor: [])
    tasks_render._render_library_dialog()
    assert "Close" in fake_st.button_labels
    assert fake_st.database_writes == []
```

Add equivalent explicit fixtures for an inaccessible task target and a task move with no compatible destination folders; each must render Close before returning and make no service mutation.

Cover operation-editor Cancel and operation-reference Close in `tests/test_task_operation_dialog.py` so “every modal” is enforced beyond folder organization.

- [ ] **Step 2: Write failing Back/Forward precedence tests**

```python
def test_back_closes_dialog_but_retains_working_copy(fake_st):
    draft = {"name": "In progress"}
    fake_st.session_state[tasks_render.K_LIBRARY_DIALOG_DRAFT] = draft
    tasks_render._restore_dialog_from_location(
        WorkspaceLocation(view="library"), set(), set()
    )
    assert fake_st.session_state[tasks_render.K_LIBRARY_DIALOG] is None
    assert fake_st.session_state[tasks_render.K_LIBRARY_DIALOG_DRAFT] == draft


def test_forward_reopens_only_valid_authorized_dialog(fake_st):
    location = WorkspaceLocation(
        view="library", dialog="folder-rename", dialog_folder_id=31,
    )
    tasks_render._restore_dialog_from_location(location, set(), {31})
    assert fake_st.session_state[tasks_render.K_LIBRARY_DIALOG] == "folder-rename"
```

Add invalid-target cases proving the dialog remains closed and produces a bounded error with Close.

- [ ] **Step 3: Run dialog tests and confirm RED**

Run: `python -m pytest tests/test_tasks_workspace_modes.py tests/test_task_operation_dialog.py -k 'dialog or modal or cancel or close or back or forward' -q`

Expected: failures for missing visible exits and URL-authoritative restoration.

- [ ] **Step 4: Implement one close routine and render footer exits before returns**

```python
def _close_library_dialog(*, discard: bool) -> None:
    st.session_state[K_LIBRARY_DIALOG] = None
    st.session_state[K_LIBRARY_DIALOG_FOLDER] = None
    st.session_state[K_LIBRARY_DIALOG_TASK] = None
    st.session_state.pop("tasks_library_dialog_error", None)
    for key in LIBRARY_DIALOG_WIDGET_KEYS:
        st.session_state.pop(key, None)
    if discard:
        st.session_state.pop(K_LIBRARY_DIALOG_DRAFT, None)
    _write_workspace_location(dataclasses.replace(
        st.session_state[K_WORKSPACE_LOCATION],
        dialog=None, dialog_task_id=None, dialog_folder_id=None,
    ))
    st.rerun()
```

Render Cancel for mutating dialogs and Close for read-only/error branches before any early return. Keep dialogs `dismissible=False`. Successful actions call the same routine with `discard=True` after persistence succeeds.

- [ ] **Step 5: Make URL state authoritative over retained drafts**

On external URL sync, clear `K_LIBRARY_DIALOG` when `dialog` is absent but preserve `K_LIBRARY_DIALOG_DRAFT`. Rehydrate widget values from that draft only when Forward supplies a valid, authorized target. Explicit Cancel deletes the retained draft, so Forward opens a clean dialog rather than resurrecting discarded input.

- [ ] **Step 6: Run all modal regressions**

Run: `python -m pytest tests/test_tasks_workspace_modes.py tests/test_task_operation_dialog.py tests/test_operation_reference_registry.py -q`

Expected: all tests pass; repository-file freshness tests may skip only when the documented source mount is absent, and the exact skip must be reported.

- [ ] **Step 7: Commit modal lifecycle changes**

```bash
git add marcedit_web/render/tasks.py tests/test_tasks_workspace_modes.py tests/test_task_operation_dialog.py
git commit -m "fix: provide explicit exits for task dialogs"
```

---

### Task 6: Contract Verification, Cataloger Help, and Ticket Closure

**Files:**
- Create: `docs/task-workspace.md`
- Modify: `README.md`
- Modify: `tests/test_task_workspace_navigation.py`
- Modify: `.tickets/TASK-193-task-library-folders-search.md`

**Interfaces:**
- Consumes: the completed navigation, workflow, filter, folder, and dialog contracts.
- Produces: a cataloger-facing workspace guide and final TASK-193 verification evidence.

- [ ] **Step 1: Add a runtime capability contract test**

```python
def test_streamlit_supports_controlled_segmented_navigation():
    signature = inspect.signature(st.segmented_control)
    assert {"options", "selection_mode", "key", "on_change"}.issubset(
        signature.parameters
    )
```

This asserts the used API rather than relying on a version string.

- [ ] **Step 2: Write the cataloger guide**

Document:

- what belongs in Run, Library, Create, and Import;
- Saved tasks versus Quick changes;
- how Apply filters and Clear filters affect Back/Forward history;
- how to create Personal and Shared folders and subfolders;
- that navigation preserves a draft only in the current browser session;
- how Discard draft differs from navigation;
- that every modal has Cancel or Close; and
- which safe state appears when a linked task, folder, or dialog is unavailable.

Link `docs/task-workspace.md` from the Tasks section of `README.md`.

- [ ] **Step 3: Run the focused TASK-193 suite**

Run:

```bash
python -m pytest \
  tests/test_task_workspace_navigation.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_task_operation_dialog.py \
  tests/test_task_library.py \
  tests/test_task_library_search.py \
  tests/test_task_db.py \
  tests/test_marcedit_import.py \
  tests/test_external_task_migration.py -q
```

Expected: zero failures. Report every skip by test name and reason; do not summarize a run containing skips as simply “all tests passed.”

- [ ] **Step 4: Run source and formatting checks**

```bash
git diff --check
python -m compileall -q marcedit_web tests
```

Expected: both commands exit 0.

- [ ] **Step 5: Run the authoritative Python 3.9 / Streamlit 1.50 Docker suite**

Run the repository's hotfix Compose test command from the execution worktree with the source mounted, using the same environment documented by TASK-194. Record passed, failed, and skipped counts separately.

Expected: zero failures. Any corpus or repository-identity skips must be named and justified; no silent skips.

- [ ] **Step 6: Perform authenticated browser acceptance at `http://localhost:8501`**

Use the configured Docker Google test account and record evidence for this exact checklist:

1. Run, Library, Create, and Import each render alone and update `view`.
2. Saved tasks and Quick changes restore through Back/Forward.
3. A folder, applied filter set, and selected task restore through Back/Forward and refresh.
4. Typing filter text creates no history entry; Apply and Clear each create one.
5. A dirty Create draft survives navigation, Back, Forward, and query-only page reinitialization.
6. An import review survives the same sequence and adopts into Create without source text entering the URL.
7. Library Edit enters Create with the stable task ID and does not change task ownership.
8. Create new folder and Create subfolder here work for Personal and Shared locations.
9. Every task-library and operation modal has Cancel or Close, including stale and no-destination cases.
10. Back closes an open modal without losing its draft; Forward reopens only a still-authorized target.
11. Inspect the URL and confirm it contains no task body, operation JSON, imported instruction, MARC record, OAuth value, or unsaved form content.

- [ ] **Step 7: Request code review and remediate every confirmed finding**

Review specifically for authorization bypass, query-key loss, history flooding, widget-state draft loss, modal resurrection, and accidental changes to TASK-192/194 behavior. Rerun the affected focused tests after each remediation and rerun Steps 3–5 after the final fix.

- [ ] **Step 8: Update the ticket and commit documentation/evidence**

Only after Steps 3–7 succeed, change TASK-193 to `Status: Completed` and add exact source-suite, Docker-suite, skip, and browser-acceptance evidence.

```bash
git add docs/task-workspace.md README.md \
  tests/test_task_workspace_navigation.py \
  .tickets/TASK-193-task-library-folders-search.md
git commit -m "docs: complete TASK-193 task workspace navigation"
```

Do not mark the ticket Completed if authenticated browser acceptance, code review, or any required test remains outstanding.
