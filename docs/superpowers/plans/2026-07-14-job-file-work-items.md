# Job File Work Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each MARC file inside a shared job an independently checkable-out, versioned, reviewable, and exportable work item, including the complete two-file Routledge workflow.

**Architecture:** SQLite remains the authority for jobs and gains `job_files`, immutable `job_file_versions`, and immutable `job_file_exports`. Candidate MARC bytes are validated on disk before a short `BEGIN IMMEDIATE` transaction rechecks checkout ownership and the opened version, inserts the new version, and swaps the file's current-version pointer. Streamlit session state caches only the selected identifiers and a `RecordStore` opened from the authoritative current version.

**Tech Stack:** Python 3.11, Streamlit, SQLite via `sqlite3`, pymarc, pytest, Docker Compose.

**Ticket:** [TASK-151](../../../.tickets/TASK-151-job-file-work-items-implementation.md)

**Design:** [Job File Work Items](../specs/2026-07-14-job-file-work-items-design.md)

## Global Constraints

- A job is the shared project; a job file is the unit of work.
- One operation acts on one file at a time.
- The original upload and every accepted version and export are immutable.
- Every mutation and export creation requires the actor's unexpired exclusive `job-file` checkout and the exact opened current-version id.
- A failure or stale version leaves the current-version pointer and prior files unchanged and removes unreferenced candidate bytes.
- Job status remains human-controlled and is never derived from file statuses.
- Existing snapshots remain readable legacy history; no new mutation may write `job_snapshots` after its path is converted.
- Use `MARCEDIT_WEB_JOB_FILES_ROOT`, defaulting to `data/job-files`, and add no dependency.
- Keep file operations streaming/disk-backed; never load a complete large batch solely to copy, version, or export it.
- Preserve unrelated working-tree changes and do not modify `missing856.txt`.

---

## File Structure

- Create `marcedit_web/lib/job_files.py`: file/version/export metadata, storage paths, attachment, atomic version adoption, workflow transitions, approval, and migration helpers.
- Modify `marcedit_web/lib/db.py`: schema version 12, tables, indexes, review/activity foreign-key columns, and idempotent upload migration.
- Modify `marcedit_web/lib/collaboration.py`: exclusive file checkout acquisition, renewal, release, force release, and in-transaction assertion.
- Modify `marcedit_web/lib/session.py`: authoritative `job_file_id`/`job_file_version_id` context and loading the current immutable version.
- Modify `marcedit_web/render/job_files.py`: job-file rows, attachment widget, checkout/status controls, history/review, and exports.
- Modify `marcedit_web/views/B_Jobs.py` and `marcedit_web/views/00_Home.py`: use the shared attachment/open-file services.
- Modify mutation renderers only at their final apply/save boundary: `single_record_edit.py`, `fixed_field_helper.py`, `edit.py`, `tasks.py`, and `validate.py`.
- Modify `marcedit_web/render/history.py`: current file-version timeline plus a separate legacy job history.
- Modify `docs/adr-collaboration-locking.md`: explicitly supersede record/job mutation locks with the per-file checkout for file-backed work.
- Add focused tests in `tests/test_job_files.py`, `tests/test_job_file_migration.py`, `tests/test_job_file_context.py`, `tests/test_job_file_mutations.py`, and `tests/test_job_file_workflow.py`; extend existing collaboration, page, history, task, and editor tests at their existing boundaries.

### Task 1: Durable job-file schema and original attachment

**Files:**
- Create: `marcedit_web/lib/job_files.py`
- Modify: `marcedit_web/lib/db.py`
- Create: `tests/test_job_files.py`
- Modify: `tests/test_job_schema.py`

**Interfaces:**
- Consumes: `db.connect()`, `jobs.require_role(job_id, user_email, allowed)`, and an already persisted source `Path`.
- Produces: `attach_file(*, job_id: int, user_email: str, source_path: Path, filename: str, record_count: int, file_bytes: int, upload_id: int | None = None, description: str = '') -> dict[str, Any]`, `list_files(job_id: int, user_email: str, include_archived: bool = False) -> list[dict[str, Any]]`, `get_file(file_id: int, user_email: str) -> dict[str, Any]`, `get_current_version(file_id: int, user_email: str) -> dict[str, Any]`, `get_version(version_id: int, user_email: str) -> dict[str, Any]`, and `versions_root() -> Path`.

- [ ] **Step 1: Write schema and attachment tests that express immutability and per-file independence**

```python
def test_attach_file_copies_original_and_creates_version_one(tmp_path):
    source = tmp_path / "incoming.mrc"
    source.write_bytes(b"first")
    job = jobs.create_job("owner@example.edu", "Routledge")

    attached = job_files.attach_file(
        job_id=job["id"], user_email="owner@example.edu",
        source_path=source, filename="deletes.mrc",
        record_count=1, file_bytes=5,
    )
    source.write_bytes(b"changed")

    current = job_files.get_current_version(attached["id"], "owner@example.edu")
    assert current["version_number"] == 1
    assert current["source_kind"] == "original"
    assert Path(current["file_path"]).read_bytes() == b"first"
    assert attached["status"] == "new"


def test_two_attachments_in_one_job_have_separate_current_versions(tmp_path):
    job = jobs.create_job("owner@example.edu", "Routledge")
    first = attach_fixture(job["id"], tmp_path, "deletes.mrc", b"one")
    second = attach_fixture(job["id"], tmp_path, "fresh.mrc", b"two")

    rows = job_files.list_files(job["id"], "owner@example.edu")
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert {row["current_version_number"] for row in rows} == {1}
```

- [ ] **Step 2: Run the focused tests and confirm the missing module/schema failure**

Run: `pytest -q tests/test_job_files.py tests/test_job_schema.py`

Expected: FAIL because `marcedit_web.lib.job_files` and the three version-12 tables do not exist.

- [ ] **Step 3: Add schema version 12 and exact constraints**

Add `SCHEMA_VERSION = 12`, call `_migrate_to_v12(conn)` after v11, and create:

```sql
CREATE TABLE IF NOT EXISTS job_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    original_upload_id INTEGER UNIQUE REFERENCES uploads(id),
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new'
      CHECK(status IN ('new','in_progress','needs_review','changes_requested',
                       'approved','exported','complete')),
    current_version_id INTEGER,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_by TEXT,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS job_file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_file_id INTEGER NOT NULL REFERENCES job_files(id),
    version_number INTEGER NOT NULL,
    parent_version_id INTEGER REFERENCES job_file_versions(id),
    file_path TEXT NOT NULL UNIQUE,
    record_count INTEGER NOT NULL CHECK(record_count >= 0),
    file_bytes INTEGER NOT NULL CHECK(file_bytes >= 0),
    source_kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL DEFAULT '{}',
    validation_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approval_kind TEXT CHECK(approval_kind IN ('self-approved','peer-approved')),
    approved_by TEXT,
    approved_at TEXT,
    UNIQUE(job_file_id, version_number)
);
CREATE INDEX IF NOT EXISTS idx_job_files_job ON job_files(job_id, id);
CREATE INDEX IF NOT EXISTS idx_job_file_versions_file
  ON job_file_versions(job_file_id, version_number DESC);
```

Create `job_file_exports` now so later tasks do not require another schema bump; use the full columns from Task 8. Add nullable `job_file_id`, `job_file_version_id`, and `job_file_export_id` columns to `job_review_notes`, and nullable `job_file_id` to `job_activity`, using `PRAGMA table_info` guards before each `ALTER TABLE`. Do not add a circular SQLite foreign key from `job_files.current_version_id`; enforce that invariant in the service transaction and cover it with tests.

- [ ] **Step 4: Implement storage paths, attachment, and read APIs**

```python
class JobFileError(ValueError):
    pass


def versions_root() -> Path:
    return Path(os.environ.get("MARCEDIT_WEB_JOB_FILES_ROOT", "data/job-files"))


def attach_file(*, job_id: int, user_email: str, source_path: Path,
                filename: str, record_count: int, file_bytes: int,
                upload_id: int | None = None,
                description: str = "") -> dict[str, Any]:
    jobs.require_role(job_id, user_email, {"owner", "editor"})
    if not filename.strip() or not source_path.is_file():
        raise JobFileError("a readable MARC file and filename are required")
    now = _utc_now_iso()
    candidate = versions_root() / "pending" / f"{uuid.uuid4().hex}.mrc"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, candidate)
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "INSERT INTO job_files(job_id,original_upload_id,display_name,description,"
                "created_by,created_at,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (job_id, upload_id, filename.strip(), description.strip(),
                 user_email, now, user_email, now),
            )
            file_id = int(cursor.lastrowid)
            target = versions_root() / str(file_id) / "versions" / "v000001.mrc"
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(candidate, target)
            version = conn.execute(
                "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
                "record_count,file_bytes,source_kind,label,created_by,created_at) "
                "VALUES(?,1,?,?,?,?,?,?,?) RETURNING id",
                (file_id, str(target), record_count, file_bytes, "original",
                 filename.strip(), user_email, now),
            ).fetchone()
            conn.execute("UPDATE job_files SET current_version_id=? WHERE id=?",
                         (version["id"], file_id))
    except Exception:
        candidate.unlink(missing_ok=True)
        if 'target' in locals():
            target.unlink(missing_ok=True)
        raise
    return get_file(file_id, user_email)
```

`list_files`, `get_file`, `get_current_version`, and `get_version` must join through `job_access`, reject inaccessible rows, expose current version/count/bytes/author/timestamp, and return plain dictionaries. Validate `file_bytes == source_path.stat().st_size` before copying.

- [ ] **Step 5: Run focused tests and the existing database suite**

Run: `pytest -q tests/test_job_files.py tests/test_job_schema.py tests/test_db.py tests/test_db_migration.py`

Expected: PASS with no skipped tests.

- [ ] **Step 6: Commit the independently usable attachment domain**

```bash
git add marcedit_web/lib/db.py marcedit_web/lib/job_files.py tests/test_job_files.py tests/test_job_schema.py
git commit -m "feat: add durable job file versions"
```

### Task 2: Shared attachment UI and authoritative file context

**Files:**
- Modify: `marcedit_web/lib/upload_persistence.py`
- Modify: `marcedit_web/lib/job_files.py`
- Modify: `marcedit_web/lib/session.py`
- Modify: `marcedit_web/render/job_files.py`
- Modify: `marcedit_web/views/B_Jobs.py`
- Modify: `marcedit_web/views/00_Home.py`
- Create: `tests/test_job_file_context.py`
- Modify: `tests/test_upload_persistence.py`
- Modify: `tests/test_job_files.py`
- Modify: `tests/test_jobs_page.py`
- Modify: `tests/test_home_page_jobs.py`
- Modify: `tests/test_session_restore.py`

**Interfaces:**
- Consumes: Task 1 read/attach APIs.
- Produces: `upload_persistence.record_upload(...) -> dict[str, Any] | None`, `session.open_job_file(file_id: int) -> dict[str, Any]`, `session.current_job_file() -> dict[str, Any] | None`, `job_files.archive_file(file_id: int, by: str) -> dict[str, Any]`, and `job_files.render_attach_file(job_id: int, user: str, role: str | None, key_prefix: str) -> None`.

- [ ] **Step 1: Write failing tests for attachment from Jobs, Home parity, and refresh restoration**

```python
def test_open_job_file_records_exact_context(monkeypatch, attached_file):
    monkeypatch.setattr(session, "current_user_id", lambda: "owner@example.edu")
    summary = session.open_job_file(attached_file["id"])
    assert summary["job_file_id"] == attached_file["id"]
    assert session.st.session_state["job_file_id"] == attached_file["id"]
    assert session.st.session_state["job_file_version_id"] == attached_file["current_version_id"]


def test_jobs_detail_renders_attach_control_for_editor(fake_jobs_page):
    fake_jobs_page.render_detail(role="editor")
    assert "Attach MARC file" in fake_jobs_page.file_uploader_labels


def test_viewer_does_not_get_attach_control(fake_jobs_page):
    fake_jobs_page.render_detail(role="viewer")
    assert "Attach MARC file" not in fake_jobs_page.file_uploader_labels
```

- [ ] **Step 2: Run focused tests and confirm the absent API/UI failures**

Run: `pytest -q tests/test_job_file_context.py tests/test_upload_persistence.py tests/test_jobs_page.py tests/test_home_page_jobs.py tests/test_session_restore.py`

Expected: FAIL because attachment is upload-only and the session has no job-file identifiers.

- [ ] **Step 3: Return the inserted upload row and attach through one shared path**

Change `record_upload` to return its inserted row using `cursor.lastrowid`; keep anonymous behavior as `None`. In `session.handle_upload`, after the durable upload and `RecordStore` have supplied the validated counts, call:

```python
upload = upload_persistence.record_upload(...)
work_file = job_files.attach_file(
    job_id=int(upload["job_id"]), user_email=user,
    source_path=Path(upload["file_path"]), filename=upload["filename"],
    record_count=int(upload["record_count"]), file_bytes=int(upload["file_bytes"]),
    upload_id=int(upload["id"]),
)
_set_job_file_context(work_file)
```

Do not let Home and Jobs create their own persistence logic. `render_attach_file` must collect the optional file description, stream via the existing uploader/session ingestion path, pass the selected job id and description, rotate the uploader nonce after success, and display the same upload feedback used on Home.

- [ ] **Step 4: Make file/version ids authoritative on open and refresh**

```python
def open_job_file(file_id: int) -> dict[str, Any]:
    user = current_user_id()
    row = job_files.get_file(file_id, user)
    version = job_files.get_current_version(file_id, user)
    store = RecordStore.from_path(Path(version["file_path"]))
    st.session_state["job_id"] = row["job_id"]
    st.session_state["job_file_id"] = row["id"]
    st.session_state["job_file_version_id"] = version["id"]
    st.session_state["record_store"] = store
    st.session_state["filename"] = row["display_name"]
    return {**row, "total": len(store), "job_file_version_id": version["id"]}


def current_job_file() -> dict[str, Any] | None:
    file_id = st.session_state.get("job_file_id")
    if file_id is None:
        return None
    try:
        return job_files.get_file(int(file_id), current_user_id())
    except job_files.JobFileError:
        detach_loaded_batch(None)
        return None
```

On `session.init`, restore `job_file_id` first; re-query access/current version and reopen its path. Use legacy `get_active_upload` restoration only when no job-file context exists. If current version changed since the cached id, load the new current version and clear mutation previews.

- [ ] **Step 5: Replace upload rows with work-file rows in the shared table**

Use `job_files.list_files`, display `display_name`, file status, `v{current_version_number}`, record count, last editor, and updated timestamp. The primary action calls `session.open_job_file(row["id"])`. Implement `archive_file` as an owner/editor action that sets `archived_by`/`archived_at`, releases its checkout, leaves every version/export on disk, and records file/job activity. Make the normal removal action call it; archived rows are omitted unless `include_archived=True`. Preserve permanent deletion only as an explicitly confirmed administrator operation that refuses deletion once versions or exports beyond the original exist.

- [ ] **Step 6: Run focused tests**

Run: `pytest -q tests/test_job_file_context.py tests/test_upload_persistence.py tests/test_jobs_page.py tests/test_home_page_jobs.py tests/test_session_restore.py tests/test_view_render.py`

Expected: PASS with Jobs and Home sharing the same attachment service.

- [ ] **Step 7: Commit file context and attachment UI**

```bash
git add marcedit_web/lib/upload_persistence.py marcedit_web/lib/job_files.py marcedit_web/lib/session.py marcedit_web/render/job_files.py marcedit_web/views/B_Jobs.py marcedit_web/views/00_Home.py tests/test_job_file_context.py tests/test_job_files.py tests/test_upload_persistence.py tests/test_jobs_page.py tests/test_home_page_jobs.py tests/test_session_restore.py
git commit -m "feat: attach and open files within jobs"
```

### Task 3: Exclusive per-file checkout

**Files:**
- Modify: `marcedit_web/lib/collaboration.py`
- Modify: `marcedit_web/lib/jobs.py`
- Modify: `marcedit_web/render/job_files.py`
- Modify: `docs/adr-collaboration-locking.md`
- Modify: `tests/test_collaboration.py`
- Modify: `tests/test_collaboration_ui_helpers.py`

**Interfaces:**
- Consumes: `job_files.get_file` and existing `locks.LockDecision`.
- Produces: `acquire_file_checkout(file_id: int, user_email: str, ttl_seconds: int = 1800) -> locks.LockDecision`, `release_file_checkout(file_id: int, user_email: str) -> bool`, `force_release_file_checkout(file_id: int, by: str) -> bool`, and `_assert_file_checkout_in_tx(conn, file_id: int, user_email: str, opened_version_id: int) -> None`.

- [ ] **Step 1: Write failing checkout tests**

```python
def test_different_catalogers_can_check_out_different_files(job_with_two_files):
    first, second = job_with_two_files
    assert collaboration.acquire_file_checkout(first["id"], OWNER).acquired
    assert collaboration.acquire_file_checkout(second["id"], EDITOR).acquired


def test_second_cataloger_can_view_but_not_check_out_same_file(shared_file):
    assert collaboration.acquire_file_checkout(shared_file["id"], OWNER).acquired
    decision = collaboration.acquire_file_checkout(shared_file["id"], EDITOR)
    assert decision.acquired is False
    assert decision.holder_email == OWNER
    assert job_files.get_file(shared_file["id"], EDITOR)["id"] == shared_file["id"]


def test_force_release_requires_owner(shared_file):
    collaboration.acquire_file_checkout(shared_file["id"], EDITOR)
    with pytest.raises(collaboration.CollaborationError, match="owner"):
        collaboration.force_release_file_checkout(shared_file["id"], by=EDITOR)
    assert collaboration.force_release_file_checkout(shared_file["id"], by=OWNER)
```

- [ ] **Step 2: Run tests and confirm file checkout APIs are absent**

Run: `pytest -q tests/test_collaboration.py tests/test_collaboration_ui_helpers.py`

Expected: FAIL on missing file checkout functions.

- [ ] **Step 3: Implement one advisory-lock resource per job file**

```python
def acquire_file_checkout(file_id: int, user_email: str,
                          ttl_seconds: int = 1800) -> locks.LockDecision:
    file_row = job_files.get_file(file_id, user_email)
    _require_editor(int(file_row["job_id"]), user_email)
    now = _now()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        decision = _acquire_lock_in_tx(
            conn, "job-file", str(file_id), user_email,
            _iso(now + dt.timedelta(seconds=ttl_seconds)), _iso(now), now,
        )
        if decision.acquired and file_row["status"] in {"new", "changes_requested"}:
            job_files._set_status_in_tx(conn, file_id, "in_progress", user_email)
        return decision


def _assert_file_checkout_in_tx(conn, file_id: int, user_email: str,
                                opened_version_id: int) -> None:
    row = _active_lock_row(conn, "job-file", str(file_id), _now())
    if row is None or row["holder_email"] != user_email:
        raise CollaborationError("file checkout is not held by this user")
    current = conn.execute(
        "SELECT current_version_id FROM job_files WHERE id=?", (file_id,)
    ).fetchone()
    if current is None or int(current["current_version_id"]) != opened_version_id:
        raise CollaborationError("file changed since this version was opened")
```

Release uses `locks.release_lock("job-file", str(file_id), user_email)`. Force release checks the parent-job owner role, deletes the exact lock in `BEGIN IMMEDIATE`, and records file/job activity. Keep legacy record/job APIs temporarily for untouched legacy code, but mark them deprecated and prohibit their use in converted mutation paths.

- [ ] **Step 4: Add checkout controls and document the superseding decision**

Show holder/expiry to all roles. Owners/editors get **Check out** or **Renew**; holders get **Done** and **Return for review**; owners get a confirmation-gated **Force release** for another holder. Update the ADR to state that TASK-151 supersedes record locks and whole-job mutation locks for job files because independence is at file scope.

- [ ] **Step 5: Verify checkout and permissions**

Run: `pytest -q tests/test_collaboration.py tests/test_collaboration_ui_helpers.py tests/test_authz.py tests/test_jobs.py`

Expected: PASS; viewer acquisition and non-owner force release fail visibly.

- [ ] **Step 6: Commit checkout scope**

```bash
git add marcedit_web/lib/collaboration.py marcedit_web/lib/jobs.py marcedit_web/render/job_files.py docs/adr-collaboration-locking.md tests/test_collaboration.py tests/test_collaboration_ui_helpers.py
git commit -m "feat: add exclusive job file checkout"
```

### Task 4: Atomic immutable version adoption

**Files:**
- Modify: `marcedit_web/lib/job_files.py`
- Modify: `marcedit_web/lib/session.py`
- Modify: `tests/test_job_files.py`
- Create: `tests/test_job_file_mutations.py`

**Interfaces:**
- Consumes: Task 3 `_assert_file_checkout_in_tx`.
- Produces: `adopt_candidate(*, file_id: int, opened_version_id: int, user_email: str, candidate_path: Path, source_kind: str, label: str, summary: dict[str, Any] | None = None, validation: dict[str, Any] | None = None) -> dict[str, Any]` and `session.adopt_current_candidate(...) -> dict[str, Any]`.

- [ ] **Step 1: Write atomicity tests before the implementation**

```python
def test_adopt_candidate_creates_version_and_swaps_current(checked_out_file, candidate):
    before = job_files.get_current_version(checked_out_file["id"], OWNER)
    created = job_files.adopt_candidate(
        file_id=checked_out_file["id"], opened_version_id=before["id"],
        user_email=OWNER, candidate_path=candidate,
        source_kind="quick-batch", label="Set leader status to deleted",
    )
    assert created["version_number"] == 2
    assert job_files.get_current_version(checked_out_file["id"], OWNER)["id"] == created["id"]
    assert Path(before["file_path"]).exists()


@pytest.mark.parametrize("failure", ["lost_checkout", "stale_version", "invalid_marc"])
def test_failed_adoption_preserves_current_and_removes_candidate(failure, scenario):
    before_id, candidate = scenario.arrange(failure)
    with pytest.raises(job_files.JobFileError):
        scenario.adopt(candidate)
    assert scenario.current_version_id() == before_id
    assert not candidate.exists()
```

- [ ] **Step 2: Run tests and confirm the adoption API failure**

Run: `pytest -q tests/test_job_files.py tests/test_job_file_mutations.py`

Expected: FAIL because `adopt_candidate` is missing.

- [ ] **Step 3: Implement validate-then-compare-and-swap adoption**

Before the transaction, index the candidate with `RecordStore.from_path`, capture record count and byte size, and reject malformed/empty output under the same rules as uploads. Then:

```python
def adopt_candidate(*, file_id: int, opened_version_id: int, user_email: str,
                    candidate_path: Path, source_kind: str, label: str,
                    summary: dict[str, Any] | None = None,
                    validation: dict[str, Any] | None = None) -> dict[str, Any]:
    owned_candidate = Path(candidate_path)
    try:
        store = RecordStore.from_path(owned_candidate)
        count, byte_count = len(store), owned_candidate.stat().st_size
        if count == 0:
            raise JobFileError("candidate contains no MARC records")
        now = _utc_now_iso()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            collaboration._assert_file_checkout_in_tx(
                conn, file_id, user_email, opened_version_id
            )
            next_number = int(conn.execute(
                "SELECT COALESCE(MAX(version_number),0)+1 AS n "
                "FROM job_file_versions WHERE job_file_id=?", (file_id,)
            ).fetchone()["n"])
            target = _version_path(file_id, next_number)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(owned_candidate, target)
            version_id = int(conn.execute(
                "INSERT INTO job_file_versions(job_file_id,version_number,parent_version_id,"
                "file_path,record_count,file_bytes,source_kind,label,summary_json,validation_json,"
                "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (file_id, next_number, opened_version_id, str(target), count, byte_count,
                 source_kind, label, json.dumps(summary or {}),
                 json.dumps(validation or {}), user_email, now),
            ).fetchone()["id"])
            changed = conn.execute(
                "UPDATE job_files SET current_version_id=?,status='in_progress',"
                "updated_by=?,updated_at=? WHERE id=? AND current_version_id=?",
                (version_id, user_email, now, file_id, opened_version_id),
            ).rowcount
            if changed != 1:
                raise JobFileError("file changed since this version was opened")
            _invalidate_approval_and_supersede_exports_in_tx(conn, file_id, version_id)
    except Exception:
        owned_candidate.unlink(missing_ok=True)
        if 'target' in locals():
            target.unlink(missing_ok=True)
        raise
    return get_version(version_id, user_email)
```

Ensure transaction rollback cannot leave a database row pointing at a missing file: on any exception after `os.replace`, move the target back to the candidate before connection rollback, then unlink it. Add an explicit test that monkeypatches the pointer update to fail after the rename.

- [ ] **Step 4: Reopen the adopted current version in session**

`session.adopt_current_candidate` reads `job_file_id` and `job_file_version_id`, calls `adopt_candidate`, then calls `open_job_file(file_id)` and clears previews. It rejects quick-load sessions with: `This change requires a file opened from a job.`

- [ ] **Step 5: Run focused and storage tests**

Run: `pytest -q tests/test_job_files.py tests/test_job_file_mutations.py tests/test_record_store.py tests/test_session.py`

Expected: PASS, including lost checkout, stale version, invalid candidate, and post-rename rollback cases.

- [ ] **Step 6: Commit the single mutation gateway**

```bash
git add marcedit_web/lib/job_files.py marcedit_web/lib/session.py tests/test_job_files.py tests/test_job_file_mutations.py
git commit -m "feat: atomically adopt immutable file versions"
```

### Task 5: Convert record and full-file editors to the version gateway

**Files:**
- Modify: `marcedit_web/render/single_record_edit.py`
- Modify: `marcedit_web/render/fixed_field_helper.py`
- Modify: `marcedit_web/render/edit.py`
- Modify: `tests/test_inline_edit_annotations.py`
- Modify: `tests/test_fixed_field_control.py`
- Modify: `tests/test_editor.py`
- Modify: `tests/test_marceditor_mode.py`
- Modify: `tests/test_job_file_mutations.py`

**Interfaces:**
- Consumes: `session.adopt_current_candidate` from Task 4.
- Produces: every accepted single-record, fixed-field, and MarcEditor save creates source kinds `record-edit`, `fixed-field`, and `marceditor` respectively; no converted path calls `RecordStore.replace_from_path`, `provenance.create_snapshot`, or `collaboration.bump_job_version`.

- [ ] **Step 1: Add failing integration tests around each existing save callback**

```python
@pytest.mark.parametrize("surface,source_kind", [
    ("single_record", "record-edit"),
    ("fixed_field", "fixed-field"),
    ("marceditor", "marceditor"),
])
def test_editor_save_adopts_one_new_version(surface, source_kind, editor_harness):
    before = editor_harness.current_version_number
    editor_harness.save_valid_change(surface)
    assert editor_harness.current_version_number == before + 1
    assert editor_harness.current_version["source_kind"] == source_kind
    assert editor_harness.original_bytes_unchanged


def test_editor_without_checkout_cannot_change_current(editor_harness):
    before = editor_harness.current_version_id
    editor_harness.release_checkout()
    editor_harness.save_valid_change("single_record")
    assert editor_harness.current_version_id == before
    assert "checkout" in editor_harness.visible_error.lower()
```

- [ ] **Step 2: Run editor tests and observe in-place mutation behavior**

Run: `pytest -q tests/test_job_file_mutations.py tests/test_inline_edit_annotations.py tests/test_fixed_field_control.py tests/test_editor.py tests/test_marceditor_mode.py`

Expected: FAIL because current callbacks mutate the loaded `RecordStore` path and use record/job versions.

- [ ] **Step 3: Route each final save through a candidate path**

At each callback, retain current parsing/validation and preview behavior, but write the complete resulting batch to the existing scratch/candidate path and finish with:

```python
session.adopt_current_candidate(
    candidate_path=candidate_path,
    source_kind="record-edit",  # fixed-field or marceditor at the other call sites
    label=operation_label,
    summary={"record_index": record_index, "changed_fields": changed_fields},
    validation=validation_summary,
)
```

Do not mutate the loaded path before adoption. On success, discard editor buffers and show the new version number. On `JobFileError`/`CollaborationError`, show the exact error and retain the buffer so the cataloger can copy or retry after reopening.

- [ ] **Step 4: Delete converted legacy history/version calls and verify by source scan**

Run: `rg -n 'create_snapshot|bump_job_version|assert_can_save_record|replace_from_path' marcedit_web/render/single_record_edit.py marcedit_web/render/fixed_field_helper.py marcedit_web/render/edit.py`

Expected: no matches in these three converted files.

- [ ] **Step 5: Run editor and collaboration tests**

Run: `pytest -q tests/test_job_file_mutations.py tests/test_inline_edit_annotations.py tests/test_fixed_field_control.py tests/test_editor.py tests/test_marceditor_mode.py tests/test_collaboration.py`

Expected: PASS with exactly one new version per accepted save.

- [ ] **Step 6: Commit converted editor mutations**

```bash
git add marcedit_web/render/single_record_edit.py marcedit_web/render/fixed_field_helper.py marcedit_web/render/edit.py tests/test_inline_edit_annotations.py tests/test_fixed_field_control.py tests/test_editor.py tests/test_marceditor_mode.py tests/test_job_file_mutations.py
git commit -m "feat: version accepted record edits"
```

### Task 6: Convert task, batch, FOLIO-fix, and restore operations

**Files:**
- Modify: `marcedit_web/render/tasks.py`
- Modify: `marcedit_web/render/validate.py`
- Modify: `marcedit_web/render/history.py`
- Modify: `tests/test_tasks_export.py`
- Modify: `tests/test_quick_replace_snapshot.py`
- Modify: `tests/test_quick_batch.py`
- Modify: `tests/test_folio_profile_fixes.py`
- Modify: `tests/test_snapshot_actions.py`
- Modify: `tests/test_job_file_mutations.py`

**Interfaces:**
- Consumes: `session.adopt_current_candidate` and `job_files.get_version`.
- Produces: explicit **Apply as new version** for saved tasks and version source kinds `task`, `quick-replace`, `quick-batch`, `folio-fix`, and `restore`.

- [ ] **Step 1: Write failing tests for preview/apply separation and restore-as-new-version**

```python
def test_saved_task_run_does_not_change_current_until_applied(task_harness):
    before = task_harness.current_version_id
    task_harness.run_successful_task()
    assert task_harness.current_version_id == before
    assert task_harness.has_button("Apply as new version")
    task_harness.click("Apply as new version")
    assert task_harness.current_version_id != before
    assert task_harness.current_version["source_kind"] == "task"


def test_restore_creates_child_of_selected_historical_bytes(history_harness):
    selected = history_harness.version(1)
    before_number = history_harness.current_version_number
    history_harness.restore(selected["id"])
    assert history_harness.current_version_number == before_number + 1
    assert history_harness.current_version["source_kind"] == "restore"
    assert history_harness.current_bytes == Path(selected["file_path"]).read_bytes()
```

- [ ] **Step 2: Run focused operation tests and confirm legacy snapshot/in-place behavior**

Run: `pytest -q tests/test_tasks_export.py tests/test_quick_replace_snapshot.py tests/test_quick_batch.py tests/test_folio_profile_fixes.py tests/test_snapshot_actions.py tests/test_job_file_mutations.py`

Expected: FAIL because tasks retain output as snapshots/exports and other operations replace the current store.

- [ ] **Step 3: Keep preview generation unchanged and replace only final acceptance**

For successful saved-task runs, keep the disk-backed result path and diff summary in session state. Render:

```python
if st.button("Apply as new version", type="primary", key="task_apply_version"):
    try:
        version = session.adopt_current_candidate(
            candidate_path=Path(results["output_path"]), source_kind="task",
            label=results["task_label"], summary=results["summary"],
            validation=results["validation"],
        )
    except (job_files.JobFileError, collaboration.CollaborationError) as exc:
        st.error(str(exc))
    else:
        st.success(f"Applied as version {version['version_number']}.")
        st.session_state.pop("task_run_results", None)
```

Use the same gateway at the final apply boundary for quick replace, quick batch, and FOLIO fixes. Restore copies the selected immutable version to a candidate and adopts it; it never changes or deletes an older row.

- [ ] **Step 4: Remove new snapshot writes from converted paths**

Run: `rg -n 'create_snapshot|replace_from_path|bump_job_version' marcedit_web/render/tasks.py marcedit_web/render/validate.py marcedit_web/render/history.py`

Expected: no matches belonging to task apply, quick replace, quick batch, FOLIO-fix apply, or restore. Legacy-history display may still call `provenance.list_snapshots`.

- [ ] **Step 5: Verify every operation's source kind and stale-check behavior**

Run: `pytest -q tests/test_tasks_export.py tests/test_quick_replace_snapshot.py tests/test_quick_batch.py tests/test_folio_profile_fixes.py tests/test_snapshot_actions.py tests/test_job_file_mutations.py tests/test_tasks_workspace_modes.py`

Expected: PASS; a preview made from an older current version cannot be applied.

- [ ] **Step 6: Commit remaining mutation paths**

```bash
git add marcedit_web/render/tasks.py marcedit_web/render/validate.py marcedit_web/render/history.py tests/test_tasks_export.py tests/test_quick_replace_snapshot.py tests/test_quick_batch.py tests/test_folio_profile_fixes.py tests/test_snapshot_actions.py tests/test_job_file_mutations.py
git commit -m "feat: apply batch work as file versions"
```

### Task 7: Per-file review, status, approval, history, and activity

**Files:**
- Modify: `marcedit_web/lib/job_files.py`
- Modify: `marcedit_web/lib/jobs.py`
- Modify: `marcedit_web/render/job_files.py`
- Modify: `marcedit_web/render/history.py`
- Modify: `marcedit_web/views/B_Jobs.py`
- Modify: `tests/test_job_files.py`
- Modify: `tests/test_jobs.py`
- Modify: `tests/test_history_render.py`
- Modify: `tests/test_jobs_page.py`

**Interfaces:**
- Consumes: current version and checkout APIs.
- Produces: `return_for_review(file_id: int, by: str) -> dict[str, Any]`, `request_changes(file_id: int, by: str, note: str) -> dict[str, Any]`, `approve_current(file_id: int, by: str) -> dict[str, Any]`, `set_complete(file_id: int, by: str) -> dict[str, Any]`, `list_versions(file_id: int, user_email: str) -> list[dict[str, Any]]`, and structured optional ids on `jobs.add_review_note`.

- [ ] **Step 1: Write transition, approval-label, and file-scoping tests**

```python
def test_peer_approval_is_bound_to_exact_current_version(shared_file):
    version = job_files.get_current_version(shared_file["id"], OWNER)
    approved = job_files.approve_current(shared_file["id"], by=EDITOR)
    assert approved["status"] == "approved"
    assert approved["current_version"]["approval_kind"] == "peer-approved"
    assert approved["current_version"]["approved_by"] == EDITOR
    assert approved["current_version"]["id"] == version["id"]


def test_new_version_invalidates_approval_but_keeps_historical_approval(approved_file):
    old = job_files.get_current_version(approved_file["id"], OWNER)
    new = adopt_checked_out_candidate(approved_file)
    assert job_files.get_file(approved_file["id"], OWNER)["status"] == "in_progress"
    assert job_files.get_version(old["id"], OWNER)["approval_kind"] == "self-approved"
    assert new["approval_kind"] is None


def test_review_notes_for_two_files_do_not_mix(job_with_two_files):
    first, second = job_with_two_files
    jobs.add_review_note(first["job_id"], anchor_kind="job_file", anchor_value="",
                         note="Check leader", author=OWNER,
                         job_file_id=first["id"], job_file_version_id=first["current_version_id"])
    assert len(jobs.list_review_notes(first["job_id"], user_email=OWNER,
                                      job_file_id=first["id"])) == 1
    assert jobs.list_review_notes(second["job_id"], user_email=OWNER,
                                  job_file_id=second["id"]) == []
```

- [ ] **Step 2: Run review/history tests and confirm missing file scope**

Run: `pytest -q tests/test_job_files.py tests/test_jobs.py tests/test_history_render.py tests/test_jobs_page.py`

Expected: FAIL because notes/history and approval are not file/version scoped.

- [ ] **Step 3: Implement exact state transitions in service functions**

Each transition checks owner/editor access and current version inside `BEGIN IMMEDIATE`, records one `job_activity` row with `job_file_id`, and returns the refreshed file. `return_for_review` requires the actor's checkout, sets `needs_review`, and releases it. `request_changes` sets `changes_requested`, writes a required note against the current version, and releases any reviewer checkout. `approve_current` writes approval fields on the current version and determines:

```python
approval_kind = (
    "self-approved" if current["created_by"] == by else "peer-approved"
)
```

It then sets file status `approved`. `set_complete` is explicit and only allowed from `approved` or `exported`.

- [ ] **Step 4: Render file-focused review and history**

Opening **History & review** shows only that file's ordered immutable versions, exact author/source/label/approval, parent diff, structured notes, and transition buttons. Under a separate **Legacy job history** heading, show `provenance.list_snapshots(job_id)` rows that were not deterministically migrated. Aggregate Job activity includes the file display name in every file event.

- [ ] **Step 5: Verify review behavior and existing job behavior**

Run: `pytest -q tests/test_job_files.py tests/test_jobs.py tests/test_history_render.py tests/test_jobs_page.py tests/test_provenance.py`

Expected: PASS; self and peer approvals are visibly distinct and historical approvals remain intact.

- [ ] **Step 6: Commit review workflow**

```bash
git add marcedit_web/lib/job_files.py marcedit_web/lib/jobs.py marcedit_web/render/job_files.py marcedit_web/render/history.py marcedit_web/views/B_Jobs.py tests/test_job_files.py tests/test_jobs.py tests/test_history_render.py tests/test_jobs_page.py
git commit -m "feat: add per-file review workflow"
```

### Task 8: Immutable labeled exports and manual load audit

**Files:**
- Modify: `marcedit_web/lib/job_files.py`
- Modify: `marcedit_web/render/job_files.py`
- Modify: `marcedit_web/render/history.py`
- Modify: `tests/test_job_files.py`
- Modify: `tests/test_tasks_export.py`
- Create: `tests/test_job_file_workflow.py`

**Interfaces:**
- Consumes: current version, checkout assertion, and approval metadata.
- Produces: `create_export(*, file_id: int, opened_version_id: int, user_email: str, purpose: str, description: str = '', filename: str | None = None) -> dict[str, Any]`, `get_export(export_id: int, user_email: str) -> dict[str, Any]`, `list_exports(file_id: int, user_email: str) -> list[dict[str, Any]]`, and `mark_export_loaded(export_id: int, *, by: str, destination: str, external_id: str = '', note: str = '') -> dict[str, Any]`.

- [ ] **Step 1: Write export lifecycle tests**

```python
def test_export_from_approved_current_version_is_ready(approved_checked_out_file):
    current = job_files.get_current_version(approved_checked_out_file["id"], OWNER)
    export = job_files.create_export(
        file_id=approved_checked_out_file["id"], opened_version_id=current["id"],
        user_email=OWNER, purpose="EDS deletion load",
        description="July Routledge withdrawal",
    )
    assert export["state"] == "ready"
    assert export["version_id"] == current["id"]
    assert Path(export["file_path"]).read_bytes() == Path(current["file_path"]).read_bytes()


def test_later_version_supersedes_unloaded_export_but_not_loaded_export(exported_file):
    ready, loaded = exported_file.ready, exported_file.loaded
    adopt_checked_out_candidate(exported_file.file)
    assert job_files.get_export(ready["id"], OWNER)["state"] == "superseded"
    assert job_files.get_export(loaded["id"], OWNER)["state"] == "loaded"


def test_mark_loaded_does_not_require_checkout(ready_export):
    collaboration.release_file_checkout(ready_export["job_file_id"], OWNER)
    loaded = job_files.mark_export_loaded(
        ready_export["id"], by=EDITOR, destination="EDS",
        external_id="load-2026-07-14", note="Accepted by EDS",
    )
    assert loaded["state"] == "loaded"
    assert loaded["loaded_by"] == EDITOR
```

- [ ] **Step 2: Run export tests and confirm missing lifecycle**

Run: `pytest -q tests/test_job_files.py tests/test_tasks_export.py tests/test_job_file_workflow.py`

Expected: FAIL because retained exports are not version-bound or labeled.

- [ ] **Step 3: Implement the export table and service**

Task 1's schema must contain:

```sql
CREATE TABLE IF NOT EXISTS job_file_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_file_id INTEGER NOT NULL REFERENCES job_files(id),
    version_id INTEGER NOT NULL REFERENCES job_file_versions(id),
    purpose TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    record_count INTEGER NOT NULL,
    validation_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL CHECK(state IN ('draft','ready','superseded','loaded')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    superseded_by_version_id INTEGER REFERENCES job_file_versions(id),
    loaded_destination TEXT,
    loaded_external_id TEXT,
    loaded_note TEXT,
    loaded_by TEXT,
    loaded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_file_exports_file
  ON job_file_exports(job_file_id, created_at DESC);
```

`create_export` requires nonblank purpose, rechecks checkout/current version in the transaction, streams the current version to a unique `exports/<uuid>-<safe-filename>` path, verifies size/count, then inserts `ready` only when the exact current version is approved; otherwise `draft`. A ready export sets file status `exported`. `mark_export_loaded` requires owner/editor parent-job access, preserves the artifact, and records destination, external id, note, actor, and timestamp without requiring checkout.

- [ ] **Step 4: Render exports under their file**

The form requires **Purpose**, accepts description and filename, and clearly labels draft/ready/superseded/loaded. Download bytes from the retained export path, not from the mutable session store. Provide **Mark loaded** with destination required and optional external id/note; completion remains a separate explicit file action.

- [ ] **Step 5: Verify export lifecycle**

Run: `pytest -q tests/test_job_files.py tests/test_tasks_export.py tests/test_job_file_workflow.py tests/test_history_render.py`

Expected: PASS; older unloaded exports supersede, loaded artifacts remain loaded, and draft is visibly distinct from ready.

- [ ] **Step 6: Commit labeled exports**

```bash
git add marcedit_web/lib/job_files.py marcedit_web/render/job_files.py marcedit_web/render/history.py tests/test_job_files.py tests/test_tasks_export.py tests/test_job_file_workflow.py
git commit -m "feat: retain labeled file exports"
```

### Task 9: Conservative migration, Routledge acceptance, and final verification

**Files:**
- Modify: `marcedit_web/lib/db.py`
- Modify: `marcedit_web/lib/job_files.py`
- Create: `tests/test_job_file_migration.py`
- Modify: `tests/test_job_file_workflow.py`
- Modify: `docs/deployment.md`
- Modify: `.tickets/TASK-151-job-file-work-items-implementation.md`

**Interfaces:**
- Consumes: all previous task interfaces.
- Produces: `_migrate_uploads_to_job_files(conn) -> None`, idempotent legacy conversion, documented storage/backup requirements, and the complete acceptance test.

- [ ] **Step 1: Write migration and end-to-end acceptance tests**

```python
def test_existing_upload_migrates_once_to_immutable_version(tmp_path):
    upload_id, original_path = seed_v11_upload(tmp_path, b"legacy")
    db.reset_for_tests(); db.init_schema()
    first = migrated_file_for_upload(upload_id)
    assert Path(first["file_path"]).read_bytes() == b"legacy"
    assert Path(first["file_path"]) != original_path

    db.reset_for_tests(); db.init_schema()
    assert migrated_file_ids_for_upload(upload_id) == [first["job_file_id"]]


def test_ambiguous_snapshot_remains_legacy_job_history(tmp_path):
    job_id = seed_job_with_two_uploads_and_unlinked_snapshot(tmp_path)
    db.reset_for_tests(); db.init_schema()
    assert snapshot_file_version_links(job_id) == []
    assert provenance.list_snapshots(job_id)[0]["id"] is not None


def test_routledge_job_handles_deletion_and_fresh_files_independently(workflow):
    job = workflow.create_job("Routledge load")
    workflow.invite_editor(job)
    deletion = workflow.attach(job, "current-routledge.mrc")
    workflow.checkout(deletion)
    workflow.quick_batch(deletion, "Set leader record status to deleted")
    workflow.return_for_review(deletion)
    workflow.peer_approve(deletion)
    deletion_export = workflow.export(deletion, "EDS deletion load")
    workflow.mark_loaded(deletion_export, "EDS")

    fresh = workflow.attach(job, "fresh-routledge.mrc")
    workflow.checkout(fresh)
    workflow.run_and_apply_task(fresh, "Routledge normalization")
    workflow.return_for_review(fresh)
    workflow.self_approve(fresh)
    replacement_export = workflow.export(fresh, "EDS replacement load")

    assert deletion["id"] != fresh["id"]
    assert workflow.file(deletion)["status"] == "exported"
    assert workflow.file(fresh)["status"] == "exported"
    assert deletion_export["version_id"] != replacement_export["version_id"]
```

- [ ] **Step 2: Run migration and acceptance tests and confirm migration is incomplete**

Run: `pytest -q tests/test_job_file_migration.py tests/test_job_file_workflow.py`

Expected: FAIL until existing uploads are copied and associated idempotently.

- [ ] **Step 3: Implement conservative v12 byte migration**

Inside `_migrate_to_v12`, create schema/columns first, then call `_migrate_uploads_to_job_files(conn)`. Select uploads with `removed_at IS NULL`, a non-null job id, and no `job_files.original_upload_id`. For each readable path, copy bytes to a pending path, rename to immutable `v000001.mrc`, create one job file/version using the upload's filename/count/bytes/user/timestamp, and set current version. `UNIQUE(original_upload_id)` plus `INSERT OR IGNORE` makes reruns safe. If a source path is missing or copy fails, log a warning containing upload id and path, create no partial row, and leave schema initialization running for other uploads. Never infer a snapshot-to-file link from job id alone.

- [ ] **Step 4: Document storage, backup, and operational limits**

In `docs/deployment.md`, add `MARCEDIT_WEB_JOB_FILES_ROOT=data/job-files`, state that the database and job-files root must be backed up/restored together, and explain that large batches remain disk-backed while concurrent operations still consume CPU, temporary disk, and worker time. State that the web workflow supports shared asynchronous handoffs and is not simultaneous Google Docs-style editing.

- [ ] **Step 5: Run focused workflow, migration, and source-gate checks**

Run: `pytest -q tests/test_job_file_migration.py tests/test_job_file_workflow.py tests/test_job_file_mutations.py tests/test_jobs_page.py tests/test_home_page_jobs.py tests/test_history_render.py`

Expected: PASS with no skipped tests.

Run: `rg -n 'create_snapshot|replace_from_path|bump_job_version|assert_can_save_record' marcedit_web/render`

Expected: no match in any accepted mutation path; any remaining match must be read-only legacy history or a non-job quick-load path and must carry a comment stating that boundary.

- [ ] **Step 6: Run the complete suite in the project runtime**

Run: `docker compose run --rm -v "$PWD:/app" -v "$PWD/tests:/app/tests" marcedit-web pytest -q`

Expected: all tests PASS, zero skipped tests, and the test count is not lower than the pre-change baseline of 1,099.

- [ ] **Step 7: Verify the cataloger workflow interactively**

Run: `npm run dev`

In the signed-in local app: create **Routledge load**; attach the current file from Jobs; invite an editor; check out and set leader status to deleted; return for review; approve; create/mark an **EDS deletion load** export; attach a fresh file to the same job; apply a saved task as a new version; approve; create an **EDS replacement load** export; refresh between handoffs; verify both files retain separate checkout, status, history, notes, approval, and exports. Expected: every action succeeds, stale/non-holder mutation is visibly blocked, and refresh restores the authoritative file/current version.

- [ ] **Step 8: Request code review and resolve findings**

Use `superpowers:requesting-code-review` against the full TASK-151 diff. Resolve every Critical and Important finding with a failing regression test first, rerun the focused test, and repeat review until none remain.

- [ ] **Step 9: Mark the ticket completed and commit final migration/docs**

Change the ticket status only after Steps 5–8 succeed:

```markdown
Status: Completed

Verification:
- Complete pytest suite: passing, zero skipped.
- Routledge two-file workflow: passing interactively.
- Code review: no unresolved Critical or Important findings.
```

Then commit:

```bash
git add marcedit_web/lib/db.py marcedit_web/lib/job_files.py tests/test_job_file_migration.py tests/test_job_file_workflow.py docs/deployment.md .tickets/TASK-151-job-file-work-items-implementation.md
git commit -m "feat: complete job file work item workflow"
```
