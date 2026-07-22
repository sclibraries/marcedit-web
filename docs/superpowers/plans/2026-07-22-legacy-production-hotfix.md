# Legacy Production Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backport the four approved production correctness fixes to the exact legacy production revision without importing durable-queue or two-service deployment changes.

**Architecture:** Work only on branch `legacy-hotfix-production-fixes`, rooted at production commit `134bc16`. Adapt the fixes directly to the legacy synchronous code, preserving the existing `marcedit-web.service` topology and deployment assets; every behavior receives a RED/GREEN regression before implementation.

**Tech Stack:** Python 3.9, stdlib `sqlite3` and `re`, pymarc 5, Streamlit, pytest, existing `marcedit-web:dev` verification image.

## Global Constraints

- Ticket: [TASK-171](../../../.tickets/TASK-171-legacy-production-hotfix.md).
- Design: [legacy hotfix design](../specs/2026-07-22-legacy-production-hotfix-design.md).
- Base commit is exactly `134bc16`; do not merge or rebase `main` into this branch.
- Preserve synchronous saved-task execution; add no durable-operation or worker code.
- Do not modify `scripts/deploy.sh`, `scripts/install.sh`, `deploy/`, sudoers, Apache configuration, systemd units, or environment templates.
- Do not modify or delete production data. `data/snapshots/` must remain untouched.
- Do not deploy production from this implementation session.
- Push only `legacy-hotfix-production-fixes`, never `main` or another worktree branch.

---

### Task 1: Backport production-SQLite shared-file attachment

**Files:**
- Modify: `tests/test_job_files.py`
- Modify: `tests/test_job_file_migration.py`
- Modify: `marcedit_web/lib/job_files.py`

**Interfaces:**
- Consumes: `db.connect()`, `jobs.grant_access()`, `job_files.attach_file()`, `job_files.list_files()`, `job_files.get_file()`, and `job_files.get_current_version()`.
- Produces: identical job-file return values using connection-local `cursor.lastrowid` rather than SQLite `RETURNING`.

- [ ] **Step 1: Add the legacy SQLite proxy before production edits**

Add this test-only helper to both test modules, importing `sqlite3` where needed:

```python
class LegacySqliteConnection:
    """Model production SQLite by rejecting post-3.34 RETURNING syntax."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, parameters=()):
        if "RETURNING" in sql.upper():
            raise sqlite3.OperationalError('near "RETURNING": syntax error')
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name):
        return getattr(self._connection, name)
```

- [ ] **Step 2: Add a failing shared-member attachment regression**

In `tests/test_job_files.py`, preserve the real `db.connect()` lifecycle while wrapping every connection:

```python
def test_shared_members_can_open_attachment_without_sqlite_returning(
    tmp_path, monkeypatch,
):
    """Every job member sees the durable file created on production SQLite."""
    original_connect = db.connect

    @contextmanager
    def legacy_connect():
        with original_connect() as connection:
            yield LegacySqliteConnection(connection)

    monkeypatch.setattr(db, "connect", legacy_connect)
    job = jobs.create_job("owner@example.edu", "Routledge load")
    jobs.grant_access(
        job["id"], "editor@example.edu", "editor", by="owner@example.edu",
    )
    jobs.grant_access(
        job["id"], "viewer@example.edu", "viewer", by="owner@example.edu",
    )

    attached = attach_fixture(
        job["id"], tmp_path, "routledge.mrc", b"record",
    )

    for member in (
        "owner@example.edu", "editor@example.edu", "viewer@example.edu",
    ):
        rows = job_files.list_files(job["id"], member)
        assert [row["id"] for row in rows] == [attached["id"]]
        assert job_files.get_file(attached["id"], member)["id"] == attached["id"]
        assert (
            job_files.get_current_version(attached["id"], member)["id"]
            == attached["current_version_id"]
        )
```

- [ ] **Step 3: Make the existing migration/idempotence regression use the proxy**

After creating the empty v12 tables, run both migration calls through one proxy on the same connection:

```python
with db.connect() as conn:
    legacy = LegacySqliteConnection(conn)
    job_files._migrate_uploads_to_job_files(legacy)
    job_files._migrate_uploads_to_job_files(legacy)
```

Keep the existing assertions for one immutable version, retained artifact bytes, metadata, and no duplicate after the source disappears.

- [ ] **Step 4: Run RED in Python 3.9**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:dev python -m pytest \
  tests/test_job_files.py::test_shared_members_can_open_attachment_without_sqlite_returning \
  tests/test_job_file_migration.py -q
```

Expected: attachment raises `sqlite3.OperationalError: near "RETURNING": syntax error`; the migration materialization assertion also fails because the proxy rejects the version insert.

- [ ] **Step 5: Replace all four runtime identity reads**

At migration, attachment, export creation, and immutable-version publication,
use these exact forms. Migration:

```python
cursor = conn.execute(
    "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
    "record_count,file_bytes,source_kind,label,created_by,created_at) "
    "VALUES(?,1,?,?,?,?,?,?,?)",
    (
        file_id, str(target), upload["record_count"], upload["file_bytes"],
        "legacy-upload", upload["filename"], upload["user_email"],
        upload["uploaded_at"],
    ),
)
version_id = int(cursor.lastrowid)
```

Attachment:

```python
cursor = conn.execute(
    "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
    "record_count,file_bytes,source_kind,label,created_by,created_at) "
    "VALUES(?,1,?,?,?,?,?,?,?)",
    (
        file_id, str(target), record_count, file_bytes, "original",
        clean_filename, user_email, now,
    ),
)
version_id = int(cursor.lastrowid)
```

Export:

```python
cursor = conn.execute(
    "INSERT INTO job_file_exports(job_file_id,version_id,purpose,description,"
    "filename,file_path,record_count,validation_json,state,created_by,created_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
    (
        file_id, opened_version_id, clean_purpose, description.strip(),
        clean_filename, str(target), int(version["record_count"]),
        version["validation_json"], state, user_email, now,
    ),
)
export_id = int(cursor.lastrowid)
```

Immutable version:

```python
cursor = conn.execute(
    "INSERT INTO job_file_versions(job_file_id,version_number,parent_version_id,"
    "file_path,record_count,file_bytes,source_kind,label,summary_json,"
    "validation_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
    (
        file_id, next_number, opened_version_id, str(target), count,
        byte_count, source_kind, label, json.dumps(summary or {}),
        json.dumps(validation or {}), user_email, now,
    ),
)
version_id = int(cursor.lastrowid)
```

Do not add a follow-up `SELECT`, change connections, or move any transaction,
savepoint, rename, reconciliation, or cleanup code.

- [ ] **Step 6: Run GREEN and static checks**

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:dev python -m pytest \
  tests/test_job_files.py tests/test_job_file_migration.py \
  tests/test_job_file_workflow.py tests/test_job_file_mutations.py \
  tests/test_collaboration.py -q
python3 -m py_compile marcedit_web/lib/job_files.py
! rg -n "RETURNING id" marcedit_web/lib/job_files.py
git diff --check
```

Expected: zero failures; report every skip and warning. The runtime SQL scan must produce no matches.

- [ ] **Step 7: Commit**

```bash
git add marcedit_web/lib/job_files.py tests/test_job_files.py tests/test_job_file_migration.py
git commit -m "fix: support legacy SQLite shared files"
```

### Task 2: Make legacy job-card counts match visible files

**Files:**
- Modify: `tests/test_jobs.py`
- Modify: `marcedit_web/lib/jobs.py`

**Interfaces:**
- Consumes: `jobs.list_job_summaries()` and `job_files.list_files()`.
- Produces: `file_count` equal to non-archived durable job files accessible in detail.

- [ ] **Step 1: Point job tests at isolated durable storage**

Import `job_files`, extend the autouse schema fixture with `tmp_path` and `monkeypatch`, and set:

```python
monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))
```

Add:

```python
def attach_job_file(job, tmp_path, filename):
    source = tmp_path / filename
    source.write_bytes(b"x")
    return job_files.attach_file(
        job_id=job["id"],
        user_email="owner@example.edu",
        source_path=source,
        filename=filename,
        record_count=1,
        file_bytes=1,
    )
```

Replace the upload fixture in `test_list_job_summaries_includes_file_and_open_note_counts` with `attach_job_file(...)` while retaining `file_count == 1`.

- [ ] **Step 2: Add mismatch regressions**

```python
def test_job_summary_does_not_count_unmaterialized_legacy_upload(tmp_path):
    """A card cannot claim a file that detail cannot render."""
    job = jobs.create_job("owner@example.edu", "Routledge load")
    upload_persistence.record_upload(
        user="owner@example.edu", filename="legacy.mrc",
        file_path=str(tmp_path / "legacy.mrc"), record_count=1,
        file_bytes=1, job_id=job["id"],
    )
    assert jobs.list_job_summaries("owner@example.edu")[0]["file_count"] == 0


def test_job_summary_count_matches_visible_non_archived_files(tmp_path):
    """Archived files stay hidden from both card and detail."""
    job = jobs.create_job("owner@example.edu", "Routledge load")
    visible = attach_job_file(job, tmp_path, "visible.mrc")
    archived = attach_job_file(job, tmp_path, "archived.mrc")
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_files SET archived_at=?,archived_by=? WHERE id=?",
            ("2026-07-22T12:00:00Z", "owner@example.edu", archived["id"]),
        )

    detail = job_files.list_files(job["id"], "owner@example.edu")
    summary = jobs.list_job_summaries("owner@example.edu")[0]
    assert [row["id"] for row in detail] == [visible["id"]]
    assert summary["file_count"] == len(detail) == 1
```

- [ ] **Step 3: Run RED**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_jobs.py -q
```

Expected: durable files count as zero, unmaterialized upload counts as one, and archived-file count disagrees with detail.

- [ ] **Step 4: Change only the summary aggregation**

Replace the upload join/count with:

```sql
COUNT(DISTINCT job_files.id) AS file_count
LEFT JOIN job_files
  ON job_files.job_id = jobs.id
 AND job_files.archived_at IS NULL
```

Keep authorization, job archive filtering, review-note aggregation, grouping, and ordering unchanged.

- [ ] **Step 5: Run GREEN, static checks, and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_jobs.py tests/test_job_files.py \
  tests/test_collaboration.py -q
python3 -m py_compile marcedit_web/lib/jobs.py
git diff --check
git add marcedit_web/lib/jobs.py tests/test_jobs.py
git commit -m "fix: align legacy job file counts"
```

### Task 3: Backport regex field matching to synchronous tasks

**Files:**
- Modify: `tests/test_transforms.py`
- Modify: `marcedit_web/lib/transforms.py`
- Modify: `tests/test_task_builder.py`
- Modify: `marcedit_web/lib/task_builder.py`
- Modify: `tests/test_tasks_workspace_modes.py`
- Modify: `marcedit_web/render/tasks.py`

**Interfaces:**
- Produces: `replace_field_subfield_and_indicators(..., *, regex=False, ignore_case=False)` and additive marker parameters with inline Save validation.
- Preserves: the legacy synchronous task runner and existing persistence APIs.

- [ ] **Step 1: Add transform regressions before implementation**

Add separate tests proving that regex mode uses `re.search`, is case-sensitive by default, supports `ignore_case=True`, replaces the complete subfield value, and compiles before mutation. Also prove exact mode remains case-sensitive even when `ignore_case=True`:

```python
before = record.as_marc()
with pytest.raises(re.error):
    transforms.replace_field_subfield_and_indicators(
        record, "035", " ", " ", "a", "(",
        " ", "9", "a", "replacement", regex=True,
    )
assert record.as_marc() == before
```

Use stored `prefix-TFeba123-suffix` with pattern `r"TFeba\d+"` to prove search rather than full-match behavior, and stored `tfeba` versus exact match `TFeba` with `regex=False, ignore_case=True` to prove exact compatibility.

- [ ] **Step 2: Run transform RED**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_transforms.py -q
```

Expected: new calls fail with unexpected keyword arguments.

- [ ] **Step 3: Implement compile-before-mutate matching**

Add keyword-only defaults and, before field iteration:

```python
flags = re.IGNORECASE if ignore_case else 0
pattern = re.compile(match_value, flags) if regex else None

def value_matches(value: str) -> bool:
    if pattern is not None:
        return pattern.search(value) is not None
    return value == match_value
```

Replace the existing equality condition with `value_matches(subfield.value)`. Do not change whole-subfield replacement or indicator behavior.

- [ ] **Step 4: Run transform GREEN and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_transforms.py -q
git add marcedit_web/lib/transforms.py tests/test_transforms.py
git commit -m "feat: support legacy regex field matching"
```

- [ ] **Step 5: Add builder, marker, and callback regressions**

Require two palette entries immediately after `match_value`:

```python
{"name": "regex", "label": "Treat match value as regex", "type": "bool", "default": False}
{"name": "ignore_case", "label": "Case-insensitive", "type": "bool", "default": False}
```

Add tests proving generated code contains `regex=True, ignore_case=True`, new markers round-trip both keys, an old marker omits both keys while rendering explicit false defaults, and enabled `match_value="("` raises `ValueError` containing `invalid match regex`.

Add a callback-level test in `tests/test_tasks_workspace_modes.py` that supplies the invalid form operation, invokes `_save_callback`, and asserts:

```python
assert saved == []
assert "invalid match regex" in fake_st.session_state[tasks_render.K_SAVE_ERROR]
```

The callback invocation must not raise.

- [ ] **Step 6: Run builder/callback RED**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_task_builder.py \
  tests/test_tasks_workspace_modes.py::test_save_callback_reports_invalid_form_regex_without_persisting -q
```

Expected: missing schema/keywords/validation failures and an uncaught builder validation path once validation is added outside the Save preflight handler.

- [ ] **Step 7: Add schema, validation, emitted flags, and inline handling**

Update the summary to “subfield value (exact or regex)” and add the two boolean parameters. In `_render_one`, read false defaults, validate enabled regex with `re.compile`, and raise:

```python
raise ValueError(f"invalid match regex: {exc}") from exc
```

Emit literal keyword flags:

```python
f"regex={lit(use_regex)}, ignore_case={lit(ignore_case)})"
```

In legacy `_save_callback`, move form operation construction and `render_ops_to_python(ops)` inside the existing preflight `try` that catches only `ValueError` and `SyntaxError`. Preserve synchronous execution and persistence behavior.

- [ ] **Step 8: Run GREEN, static checks, and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest \
  tests/test_task_builder.py tests/test_transforms.py tests/test_tasks.py \
  tests/test_tasks_workspace_modes.py tests/test_note_task_draft.py -q
python3 -m py_compile marcedit_web/lib/task_builder.py \
  marcedit_web/lib/transforms.py marcedit_web/render/tasks.py
git diff --check
git add marcedit_web/lib/task_builder.py marcedit_web/render/tasks.py \
  tests/test_task_builder.py tests/test_tasks_workspace_modes.py
git commit -m "feat: expose legacy regex field matching"
```

### Task 4: Backport non-mutating MARC order diagnostics

**Files:**
- Modify: `tests/test_viewer.py`
- Modify: `marcedit_web/lib/viewer.py`
- Modify: `tests/test_view_render.py`
- Modify: `marcedit_web/render/view.py`

**Interfaces:**
- Produces: `field_order_inversions(record, *, limit=20) -> list[tuple[str, str]]`.
- Preserves: `render_record_human(record, fields=tag_filter)` source order.

- [ ] **Step 1: Add helper and source-order tests**

Build records in explicit order and assert ascending silence, `[("040", "035")]` for one inversion, repeated-tag silence, three results with `limit=3`, byte-for-byte non-mutation, and rendered offsets preserving `001`, `040`, `035`, `245`.

- [ ] **Step 2: Run helper RED**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_viewer.py -q
```

Expected: `AttributeError` for the missing helper.

- [ ] **Step 3: Implement the pure bounded helper**

```python
def field_order_inversions(
    record: Record, *, limit: int = 20,
) -> list[tuple[str, str]]:
    """Return bounded adjacent descending tags without changing the record."""
    if limit <= 0:
        return []
    inversions = []
    for previous, current in zip(record.fields, record.fields[1:]):
        if current.tag < previous.tag:
            inversions.append((previous.tag, current.tag))
            if len(inversions) >= limit:
                break
    return inversions
```

- [ ] **Step 4: Run helper GREEN and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_viewer.py -q
git add marcedit_web/lib/viewer.py tests/test_viewer.py
git commit -m "feat: detect legacy MARC order inversions"
```

- [ ] **Step 5: Add behavioral View tests before changing View**

Use the existing `view.render()` path with a one-record fake store and narrow Streamlit mocks. Capture warning and human-render events, then assert:

```python
assert warnings == []
assert events == ["render"]
```

for ascending input; for `001,040,035,245` assert one warning containing `displayed in source order` and `040 before 035`, with events `['warning', 'render']`; for 22 descending tags assert exactly 20 occurrences of ` before `.

- [ ] **Step 6: Run View RED**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_view_render.py -q
```

Expected: inverted and bounded-warning tests fail because no order warning is emitted.

- [ ] **Step 7: Add one warning before unchanged rendering**

Immediately before the existing human renderer call:

```python
inversions = viewer.field_order_inversions(record)
if inversions:
    transitions = ", ".join(
        f"{previous} before {current}" for previous, current in inversions
    )
    st.warning(
        "Fields are displayed in source order, but tag order decreases at: "
        + transitions
    )
```

Do not alter `record.fields`, filtering, or the renderer call.

- [ ] **Step 8: Run GREEN, static checks, and commit**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev \
  python -m pytest tests/test_viewer.py tests/test_view_render.py \
  tests/test_view_edit.py -q
python3 -m py_compile marcedit_web/lib/viewer.py marcedit_web/render/view.py
git diff --check
git add marcedit_web/lib/viewer.py marcedit_web/render/view.py \
  tests/test_viewer.py tests/test_view_render.py
git commit -m "feat: warn on legacy MARC order inversions"
```

### Task 5: Prove legacy scope, review, document, and publish

**Files:**
- Modify: `.tickets/TASK-171-legacy-production-hotfix.md`
- No production deployment files may change.

**Interfaces:**
- Produces: reviewed branch `legacy-hotfix-production-fixes` and a manual deployment handoff.

- [ ] **Step 1: Run the combined regression gate**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest \
  tests/test_job_files.py tests/test_job_file_migration.py \
  tests/test_job_file_workflow.py tests/test_job_file_mutations.py \
  tests/test_collaboration.py tests/test_jobs.py tests/test_task_builder.py \
  tests/test_transforms.py tests/test_tasks.py tests/test_tasks_workspace_modes.py \
  tests/test_note_task_draft.py tests/test_viewer.py tests/test_view_render.py \
  tests/test_view_edit.py -q
```

Record exact pass, skip, and warning counts.

- [ ] **Step 2: Run the complete Python 3.9 suite and compilation**

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest -q
docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPYCACHEPREFIX=/tmp/pycache marcedit-web:dev \
  python -m compileall -q marcedit_web tests
git diff --check 134bc16...HEAD
git status --short
```

Expected: zero failures, compilation/diff clean, and no uncommitted tracked changes.

- [ ] **Step 3: Audit prohibited scope mechanically**

```bash
git diff --name-only 134bc16...HEAD
```

Fail the task if the list contains `scripts/deploy.sh`, `scripts/install.sh`, `.env.example`, any path below `deploy/`, any operation/worker module, or any unrelated production file. Confirm no commit from `main` was merged and `git merge-base HEAD main` does not replace the fixed base audit against `134bc16`.

- [ ] **Step 4: Request independent review**

Review `134bc16...HEAD` against TASK-171 and the design. Require explicit checks for SQLite 3.34 compatibility, shared member visibility, count/detail consistency, synchronous task preservation, invalid-regex inline handling, MARC non-mutation/order, prohibited deployment scope, and test intent. Resolve every Critical and Important finding and rerun affected tests.

- [ ] **Step 5: Complete TASK-171 evidence**

Append exact RED/GREEN commands and results, complete-suite counts/skips, static and prohibited-scope checks, commit hashes, and clean review verdict. Set `Status: Completed` only after review is clean.

```bash
git add .tickets/TASK-171-legacy-production-hotfix.md
git commit -m "docs: complete TASK-171 hotfix evidence"
```

- [ ] **Step 6: Push only the hotfix branch**

```bash
git push -u origin legacy-hotfix-production-fixes:legacy-hotfix-production-fixes
```

Verify `origin/main` did not move and other worktree branches were not pushed.

- [ ] **Step 7: Provide manual production commands without executing them**

The handoff must explicitly preserve `data/snapshots/`, avoid `scripts/deploy.sh`, fetch/switch only the hotfix branch, fast-forward from that branch, refresh the existing venv, restart only `marcedit-web`, verify HTTP health, and include rollback to `134bc16`. Production execution remains the user's action.
