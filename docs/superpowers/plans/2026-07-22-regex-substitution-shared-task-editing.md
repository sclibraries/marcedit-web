# Regex Substitution and Shared-Task Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct regex replacement so unmatched subfield text is retained, and permit safe in-place corrections to shared tasks without transferring ownership or allowing destructive collaborator actions.

**Architecture:** Regex mode will use one compiled pattern and `subn` while exact mode retains whole-value replacement. Shared collaborative edits will use a dedicated atomic storage API that compares the opened row snapshot inside `BEGIN IMMEDIATE`; the Tasks editor will preserve owner/name/visibility, enforce form-versus-admin-code policy at save time, and audit both actor and owner.

**Tech Stack:** Python 3.9, pymarc, SQLite, Streamlit, pytest, Docker.

## Global Constraints

- Ticket: [TASK-172](../../../.tickets/TASK-172-hotfix-regex-substitution-shared-task-editing.md).
- Design: [approved specification](../specs/2026-07-22-regex-substitution-shared-task-editing-design.md).
- Work only on `legacy-hotfix-production-fixes`; do not merge or rebase `main`.
- Exact mode continues to replace the complete matching subfield value.
- Regex mode replaces every matched span and preserves unmatched text on both sides.
- Invalid regexes fail before task persistence or record mutation.
- A collaborator may edit shared form tasks; only admins may collaboratively edit shared raw-code tasks.
- Collaborators cannot rename, change visibility, delete, or transfer ownership.
- Reject stale collaborative saves atomically; do not add a schema migration.
- Preserve Python 3.9 and production SQLite compatibility.
- Do not change durable operations, workers, deployment scripts, systemd, sudoers, Apache, or environment templates.
- Do not deploy production from this plan.

---

### Task 1: Substitute only regex-matched subfield spans

**Files:**
- Modify: `tests/test_transforms.py`
- Modify: `marcedit_web/lib/transforms.py`
- Modify: `tests/test_task_builder.py`
- Modify: `marcedit_web/lib/task_builder.py`

**Interfaces:**
- Preserves: `replace_field_subfield_and_indicators(..., *, regex=False, ignore_case=False) -> None`.
- Changes only regex-mode semantics from whole-value replacement to `re.sub`-style matched-span replacement.

- [ ] **Step 1: Write the failing production-case and regex-semantics tests**

Replace the old regex whole-value expectation and add explicit tests equivalent to:

```python
def test_replace_field_subfield_and_indicators_regex_preserves_unmatched_isbn():
    record = _record_with_035("TFeba9780020306634")

    transforms.replace_field_subfield_and_indicators(
        record, "035", " ", " ", "a", "TFeba",
        " ", "9", "a", "(SCTFEBA)", regex=True,
    )

    field = record.get_fields("035")[0]
    assert list(field.indicators) == [" ", "9"]
    assert field.get_subfields("a") == ["(SCTFEBA)9780020306634"]


def test_replace_field_subfield_and_indicators_regex_preserves_both_sides():
    record = _record_with_035("prefix-TFeba123-suffix")
    transforms.replace_field_subfield_and_indicators(
        record, "035", " ", " ", "a", r"TFeba\d+",
        " ", "9", "a", "replacement", regex=True,
    )
    assert record.get_fields("035")[0].get_subfields("a") == [
        "prefix-replacement-suffix"
    ]


def test_replace_field_subfield_and_indicators_regex_replaces_every_match():
    record = _record_with_035("TFeba-one-TFeba-two")
    transforms.replace_field_subfield_and_indicators(
        record, "035", " ", " ", "a", "TFeba",
        " ", "9", "a", "X", regex=True,
    )
    assert record.get_fields("035")[0].get_subfields("a") == ["X-one-X-two"]


def test_replace_field_subfield_and_indicators_regex_expands_capture_references():
    record = _record_with_035("TFeba9780020306634")
    transforms.replace_field_subfield_and_indicators(
        record, "035", " ", " ", "a", r"TFeba(\d+)",
        " ", "9", "a", r"(SCTFEBA)\1", regex=True,
    )
    assert record.get_fields("035")[0].get_subfields("a") == [
        "(SCTFEBA)9780020306634"
    ]
```

Keep the current exact-mode, case-sensitivity, ignore-case, and invalid-pattern non-mutation tests unchanged. Add a local `_record_with_035` test helper only if it reduces duplication within `tests/test_transforms.py`.

- [ ] **Step 2: Run RED and confirm the production symptom**

Run:

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_transforms.py -q
```

Expected: the new substring tests fail because the current function returns only the replacement text; existing exact and invalid-regex tests still pass.

- [ ] **Step 3: Implement one-pass regex substitution**

Replace the selector-plus-whole-value branch with the following shape:

```python
for subfield in field.subfields:
    if subfield.code != match_code:
        subfields.append(subfield)
        continue

    if pattern is not None:
        value, replacements = pattern.subn(new_value, subfield.value)
        if replacements == 0:
            subfields.append(subfield)
            continue
    else:
        if subfield.value != match_value:
            subfields.append(subfield)
            continue
        value = new_value

    subfields.append(Subfield(code=new_code, value=value))
    updated = True
```

Compile the pattern before iterating over fields exactly as today. Do not change tag, indicator, or subfield-code matching.

- [ ] **Step 4: Add explicit form help and its regression test**

Add palette help text to `match_value`, `regex`, and `new_value`:

```python
{
    "name": "match_value",
    "label": "Match subfield value",
    "type": "text",
    "required": True,
    "help": (
        "Exact mode matches the complete subfield value. Regex mode treats "
        "this as a pattern within the value."
    ),
},
{
    "name": "regex",
    "label": "Treat match value as regex",
    "type": "bool",
    "default": False,
    "help": "Replace every regex match while retaining unmatched text.",
},
{
    "name": "new_value",
    "label": "New subfield value",
    "type": "text",
    "required": True,
    "help": (
        "Exact mode replaces the complete value. Regex mode uses this as "
        "replacement text and supports capture references such as \\1."
    ),
},
```

Update the strict palette-shape test and assert these help strings contain `complete`, `retaining unmatched text`, and `capture references`. Do not add a new operation or change generated task markers.

- [ ] **Step 5: Run GREEN and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest \
  tests/test_transforms.py tests/test_task_builder.py -q
python3 -m py_compile marcedit_web/lib/transforms.py \
  marcedit_web/lib/task_builder.py
git diff --check
git add marcedit_web/lib/transforms.py marcedit_web/lib/task_builder.py \
  tests/test_transforms.py tests/test_task_builder.py
git commit -m "fix: preserve unmatched regex subfield text"
```

Expected: all selected tests pass with no skips or warning summary.

### Task 2: Add atomic shared-task correction storage

**Files:**
- Modify: `tests/test_task_db.py`
- Modify: `marcedit_web/lib/task_db.py`

**Interfaces:**
- Produces: `task_edit_snapshot(row: dict) -> dict[str, str]`.
- Produces: `update_shared_task(*, actor, owner, name, description, body, extra_imports, expected) -> None`.
- Raises: `ValueError` with a user-facing reason for missing, unshared, stale, or invalid collaborative updates.

- [ ] **Step 1: Write failing storage authorization and conflict tests**

Add tests that use the real test SQLite database:

```python
def test_update_shared_task_preserves_identity_and_visibility():
    _save("owner@example.edu", "cleanup", body="old\n",
          description="old", visibility="shared")
    before = task_db.get_task("owner@example.edu", "cleanup")

    task_db.update_shared_task(
        actor="editor@example.edu",
        owner="owner@example.edu",
        name="cleanup",
        description="corrected",
        body="new\n",
        extra_imports=["from marcedit_web.lib.transforms import delete_tags"],
        expected=task_db.task_edit_snapshot(before),
    )

    after = task_db.get_task("owner@example.edu", "cleanup")
    assert after["id"] == before["id"]
    assert after["owner_email"] == "owner@example.edu"
    assert after["name"] == "cleanup"
    assert after["visibility"] == "shared"
    assert after["created_at"] == before["created_at"]
    assert after["description"] == "corrected"
    assert after["body"] == "new\n"


def test_update_shared_task_rejects_same_second_stale_snapshot(monkeypatch):
    monkeypatch.setattr(task_db, "_utc_now", lambda: "2026-07-22T12:00:00Z")
    _save("owner@example.edu", "cleanup", body="opened\n", visibility="shared")
    opened = task_db.get_task("owner@example.edu", "cleanup")
    _save("owner@example.edu", "cleanup", body="newer\n", visibility="shared")

    with pytest.raises(ValueError, match="changed since you opened"):
        task_db.update_shared_task(
            actor="editor@example.edu", owner="owner@example.edu",
            name="cleanup", description="stale", body="stale\n",
            extra_imports=None,
            expected=task_db.task_edit_snapshot(opened),
        )

    assert task_db.get_task("owner@example.edu", "cleanup")["body"] == "newer\n"
```

Also add separate tests proving: private task rejected, task unshared after opening rejected, deleted task rejected, blank actor rejected, and owner cannot use the collaborator-only API. Each failure must leave the persisted row unchanged.

- [ ] **Step 2: Run storage RED**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_task_db.py -q
```

Expected: new tests fail with missing `task_edit_snapshot` / `update_shared_task` attributes.

- [ ] **Step 3: Implement snapshot comparison and atomic update**

Add a stable snapshot helper:

```python
_EDIT_SNAPSHOT_FIELDS = (
    "description", "body", "extra_imports", "visibility", "updated_at",
)


def task_edit_snapshot(row: dict[str, Any]) -> dict[str, str]:
    return {field: str(row.get(field) or "") for field in _EDIT_SNAPSHOT_FIELDS}
```

Add the collaborator-only mutation:

```python
def update_shared_task(
    *,
    actor: str,
    owner: str,
    name: str,
    description: str,
    body: str,
    extra_imports: Iterable[str] | None,
    expected: dict[str, str],
) -> None:
    if not actor:
        raise ValueError("signed-in cataloger required to edit a shared task")
    if actor == owner:
        raise ValueError("task owner must use the owner save path")
    extras = "\n".join(extra_imports or [])
    now = _utc_now()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM tasks WHERE owner_email = ? AND name = ?",
            (owner, name),
        ).fetchone()
        current = _row_to_dict(row)
        if current is None:
            raise ValueError("shared task was removed; reopen the task list")
        if current["visibility"] != "shared":
            raise ValueError("task is no longer shared; reopen the task list")
        if task_edit_snapshot(current) != expected:
            raise ValueError(
                "shared task changed since you opened it; reopen and try again"
            )
        conn.execute(
            "UPDATE tasks SET description = ?, body = ?, extra_imports = ?,"
            " updated_at = ? WHERE owner_email = ? AND name = ?",
            (description, body, extras, now, owner, name),
        )
```

Do not accept new owner/name/visibility values in this API. Match existing transaction and error conventions; do not add tables or columns.

- [ ] **Step 4: Run GREEN and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_task_db.py -q
python3 -m py_compile marcedit_web/lib/task_db.py
git diff --check
git add marcedit_web/lib/task_db.py tests/test_task_db.py
git commit -m "feat: update shared tasks without ownership transfer"
```

### Task 3: Expose authorized shared editing in the Tasks workspace

**Files:**
- Create: `tests/test_shared_task_editing.py`
- Modify: `tests/test_tasks_workspace_modes.py`
- Modify: `marcedit_web/render/tasks.py`

**Interfaces:**
- Consumes: `task_db.task_edit_snapshot` and `task_db.update_shared_task` from Task 2.
- Produces: `_can_edit_visible_task(row, user, is_admin) -> bool`.
- Adds editor state for original owner, opened snapshot, and collaborative-edit status.

- [ ] **Step 1: Write failing authorization-matrix tests**

Create focused tests equivalent to:

```python
import pytest

from marcedit_web.lib import task_builder
from marcedit_web.lib.task_builder import Operation


@pytest.fixture
def tasks_render(monkeypatch):
    fake_st = _FakeStreamlit()
    return _tasks_render(monkeypatch, fake_st)


def _form_row(*, owner: str, visibility: str) -> dict:
    rendered = task_builder.render_ops_to_python([
        Operation(kind="delete-tag", params={"tag": "029"})
    ])
    return {
        "id": 1,
        "owner_email": owner,
        "name": "cleanup",
        "description": "Remove vendor field",
        "body": rendered["body"],
        "extra_imports": "\n".join(rendered["imports"]),
        "visibility": visibility,
        "updated_at": "2026-07-22T12:00:00Z",
    }


def _code_row(*, owner: str, visibility: str) -> dict:
    row = _form_row(owner=owner, visibility=visibility)
    row["body"] = "record.remove_fields('029')\n"
    return row


def test_shared_form_task_is_editable_by_non_owner(tasks_render):
    row = _form_row(owner="owner@example.edu", visibility="shared")
    assert tasks_render._can_edit_visible_task(
        row, "editor@example.edu", is_admin=False
    ) is True


def test_shared_code_task_requires_admin_for_non_owner(tasks_render):
    row = _code_row(owner="owner@example.edu", visibility="shared")
    assert tasks_render._can_edit_visible_task(
        row, "editor@example.edu", is_admin=False
    ) is False
    assert tasks_render._can_edit_visible_task(
        row, "admin@example.edu", is_admin=True
    ) is True


def test_private_task_is_not_editable_by_non_owner(tasks_render):
    row = _form_row(owner="owner@example.edu", visibility="private")
    assert tasks_render._can_edit_visible_task(
        row, "editor@example.edu", is_admin=True
    ) is False
```

Also prove owners retain edit access and that the build-list renderer offers Edit but not Share/Unshare/Delete controls to an eligible non-owner. Use narrow fake columns whose button calls are captured; do not assert source text.

Include two shared rows with the same task name but different row IDs in the
list test. Action widget keys must include the stable row ID (for example,
`edit_17`) so enabling collaborator buttons cannot introduce duplicate
Streamlit keys.

- [ ] **Step 2: Write failing collaborative callback tests**

Populate editor state with `K_EDITOR_OWNER`, `K_EDITOR_SNAPSHOT`, original name, and a shared form operation. Assert that a collaborator save:

```python
assert updates[0]["actor"] == "editor@example.edu"
assert updates[0]["owner"] == "owner@example.edu"
assert updates[0]["name"] == "cleanup"
assert owner_saves == []
assert deletes == []
assert audits[-1][1]["task_owner"] == "owner@example.edu"
assert audits[-1][1]["collaborative_edit"] is True
```

Set hacked widget state to a different name and private visibility; assert the dedicated update still receives the original name and no visibility argument. Add callback tests proving:

- `update_shared_task` stale errors populate `K_SAVE_ERROR` and do not close the editor or reload the registry;
- a non-admin collaborator cannot save a shared raw-code task even if session state is manipulated to code mode;
- an admin collaborator can save shared raw code and emits `admin-action` with `task_owner`;
- the existing owner-save callback still calls `save_task` and retains rename behavior.

- [ ] **Step 3: Run UI RED**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest \
  tests/test_shared_task_editing.py tests/test_tasks_workspace_modes.py -q
```

Expected: failures show missing authorization helper/state and the current collaborator read-only branch.

- [ ] **Step 4: Implement the authorization helper and list controls**

Use task markers, not ownership assumptions, to classify shared tasks:

```python
def _can_edit_visible_task(row: dict, user: str, is_admin: bool) -> bool:
    if row["owner_email"] == user:
        return True
    if row["visibility"] != "shared":
        return False
    parsed = task_builder.parse_ops_from_source(row["body"])
    return bool(parsed["form_editable"] or is_admin)
```

In the visible-task loop, show Edit when this helper returns true. Continue to show Share/Unshare and Delete only when `owned` is true. Keep ineligible shared code tasks labeled read-only.

- [ ] **Step 5: Store immutable collaborative editor context**

Add and initialize:

```python
K_EDITOR_OWNER = "tasks_editor_owner"
K_EDITOR_SNAPSHOT = "tasks_editor_snapshot"
K_EDITOR_COLLABORATIVE = "tasks_editor_collaborative"
```

New-task state sets owner/snapshot to `None` and collaborative to `False`.
Change `_open_editor_for_existing_row` to accept the current user and set:

```python
st.session_state[K_EDITOR_OWNER] = row["owner_email"]
st.session_state[K_EDITOR_SNAPSHOT] = task_db.task_edit_snapshot(row)
st.session_state[K_EDITOR_COLLABORATIVE] = (
    row["owner_email"] != current_user
)
```

Pass `current_user_id` from the list callsite. In `_render_editor`, disable the task-name and visibility widgets for collaborative edits, state that the owner retains rename/visibility/delete control, and leave description and task operations editable.

- [ ] **Step 6: Route collaborative saves through the atomic API**

At callback start, derive the authoritative identity:

```python
task_owner = st.session_state.get(K_EDITOR_OWNER) or user
collaborative = bool(
    st.session_state.get(K_EDITOR_COLLABORATIVE) and task_owner != user
)
snapshot = st.session_state.get(K_EDITOR_SNAPSHOT)
if collaborative:
    name = original or ""
    visibility = "shared"
```

Before compiling collaborative code, recheck:

```python
if collaborative and not isinstance(snapshot, dict):
    st.session_state[K_SAVE_ERROR] = "Shared task must be reopened before saving."
    return
if collaborative and not task_admin.is_admin(user):
    opened = task_builder.parse_ops_from_source(snapshot.get("body", ""))
    if mode != "form" or not opened["form_editable"]:
        st.session_state[K_SAVE_ERROR] = (
            "Only an administrator can edit a shared code task."
        )
        return
```

After successful preflight, branch without invoking owner rename/delete logic:

```python
if collaborative:
    task_db.update_shared_task(
        actor=user,
        owner=task_owner,
        name=name,
        description=description,
        body=body,
        extra_imports=extra_imports,
        expected=snapshot,
    )
else:
    # retain the existing owner rename/delete/save block unchanged
```

Catch `ValueError` through the existing inline error path. On success, materialize/reload the actor's visible tasks. Add `task_owner=task_owner` and `collaborative_edit=collaborative` to `task-saved`; add `task_owner` to collaborative admin `admin-action`. Reset the new editor keys on successful save, cancel, new-task open, and AI-draft open.

- [ ] **Step 7: Run GREEN, regression suites, and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest \
  tests/test_shared_task_editing.py tests/test_tasks_workspace_modes.py \
  tests/test_task_db.py tests/test_task_builder.py tests/test_tasks.py \
  tests/test_note_task_draft.py tests/test_ai_task_draft.py \
  tests/test_task_import_traversal.py -q
python3 -m py_compile marcedit_web/render/tasks.py
git diff --check
git add marcedit_web/render/tasks.py tests/test_shared_task_editing.py \
  tests/test_tasks_workspace_modes.py
git commit -m "feat: allow safe shared task corrections"
```

### Task 4: Review, complete evidence, and publish the hotfix update

**Files:**
- Modify: `.tickets/TASK-172-hotfix-regex-substitution-shared-task-editing.md`

**Interfaces:**
- Produces: reviewed `legacy-hotfix-production-fixes` update and a production handoff.

- [ ] **Step 1: Run the combined TASK-171/TASK-172 regression gate**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest \
  tests/test_job_files.py tests/test_job_file_migration.py \
  tests/test_job_file_workflow.py tests/test_job_file_mutations.py \
  tests/test_collaboration.py tests/test_jobs.py tests/test_task_db.py \
  tests/test_task_builder.py tests/test_transforms.py tests/test_tasks.py \
  tests/test_tasks_workspace_modes.py tests/test_shared_task_editing.py \
  tests/test_note_task_draft.py tests/test_viewer.py tests/test_view_render.py \
  tests/test_view_edit.py -q
```

Record exact pass, fail, skip, and warning counts.

- [ ] **Step 2: Run the complete Python 3.9 and static gates**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest -q
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPYCACHEPREFIX=/tmp/pycache marcedit-web:dev \
  python -m compileall -q marcedit_web tests
git diff --check 83b1daf...HEAD
git status --short
```

Expected: zero failures, zero hidden skips, compilation/diff clean, and no uncommitted tracked changes before ticket evidence.

- [ ] **Step 3: Audit prohibited scope mechanically**

```bash
git diff --name-only 83b1daf...HEAD
git log --merges --oneline 83b1daf..HEAD
git merge-base 83b1daf HEAD
```

Fail if the path list contains deployment/environment files, worker/operation modules, job-file code, or unrelated production files. Require no merge commits and exact base `83b1daf`.

- [ ] **Step 4: Request independent whole-range review**

Review `83b1daf...HEAD` against TASK-172 and the approved design. Require explicit checks for substring semantics, exact compatibility, capture references, invalid-regex safety, the complete authorization matrix, raw-code admin guard, stale-save atomicity, identity/visibility preservation, audit actor/owner distinction, Python 3.9, test intent, and prohibited scope. Resolve every Critical and Important finding and rerun affected tests.

- [ ] **Step 5: Complete ticket evidence and commit**

Append exact RED/GREEN results, full-suite counts, static/scope checks, commits, and review verdict to TASK-172. Set `Status: Completed` only after the review is clean.

```bash
git add .tickets/TASK-172-hotfix-regex-substitution-shared-task-editing.md
git commit -m "docs: complete TASK-172 hotfix evidence"
```

- [ ] **Step 6: Push only the updated hotfix branch**

```bash
git push origin legacy-hotfix-production-fixes:legacy-hotfix-production-fixes
```

Verify local HEAD equals `origin/legacy-hotfix-production-fixes` and `origin/main` did not move. Do not deploy production; provide branch-specific manual update and rollback commands for the user.
