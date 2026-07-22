# TASK-167 SQLite Job-File Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every job-file identity insert work on production SQLite without changing transaction or cleanup semantics.

**Architecture:** Keep each insert and `cursor.lastrowid` read on the same existing SQLite connection. Preserve all current `BEGIN IMMEDIATE`, savepoint, filesystem publication, rollback, and uncertain-commit logic; change only unsupported identity retrieval.

**Tech Stack:** Python 3.9, stdlib `sqlite3`, pytest, existing `db.connect()` context manager.

## Global Constraints

- Ticket: [TASK-167](../../../.tickets/TASK-167-sqlite-shared-job-attach-compatibility.md).
- Work only in branch `prod-fixes-task-167-170`; never edit or commit on `main`.
- Production SQLite is older than 3.35 and must not receive a `RETURNING` clause.
- Add no dependency and no SQLite version upgrade requirement.
- Preserve connection-local identity allocation, transaction boundaries, commit-uncertainty recovery, and filesystem cleanup.
- Do not deploy or edit the production database.

---

### Task 1: Reproduce pre-3.35 attachment and migration failures

**Files:**
- Modify: `tests/test_job_files.py`
- Modify: `tests/test_job_file_migration.py`

**Interfaces:**
- Consumes: `db.connect()`, `job_files.attach_file(*, job_id, user_email, source_path, filename, record_count, file_bytes, upload_id=None, description="") -> dict[str, Any]`, and `job_files._migrate_uploads_to_job_files(conn) -> None`.
- Produces: a test-only connection proxy that raises `sqlite3.OperationalError` whenever runtime SQL contains `RETURNING`.

- [ ] **Step 1: Add the test-only legacy SQLite proxy**

Add this local helper to both test modules (do not add it to production code):

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

- [ ] **Step 2: Add a failing shared-job attachment regression**

In `tests/test_job_files.py`, wrap every `db.connect()` call for the test while preserving the real context-manager lifecycle:

```python
def test_attach_file_works_without_sqlite_returning(tmp_path, monkeypatch):
    """RHEL production SQLite must attach a visible immutable version."""
    original_connect = db.connect

    @contextmanager
    def legacy_connect():
        with original_connect() as connection:
            yield LegacySqliteConnection(connection)

    monkeypatch.setattr(db, "connect", legacy_connect)
    job = jobs.create_job("owner@example.edu", "Routledge load")
    attached = attach_fixture(job["id"], tmp_path, "routledge.mrc", b"record")

    assert attached["display_name"] == "routledge.mrc"
    assert attached["current_version_id"] is not None
    assert len(job_files.list_files(job["id"], "owner@example.edu")) == 1
```

- [ ] **Step 3: Make one migration regression use the proxy**

In the migration test that creates one legacy upload and asserts version 1 is materialized, pass `LegacySqliteConnection(conn)` into both migration calls:

```python
with db.connect() as conn:
    legacy = LegacySqliteConnection(conn)
    job_files._migrate_uploads_to_job_files(legacy)
    job_files._migrate_uploads_to_job_files(legacy)
```

Keep its existing assertions that one file/version exists, the artifact bytes are retained, and the rerun creates no duplicate.

- [ ] **Step 4: Run the two regressions and verify RED**

Run:

```bash
python3 -m pytest tests/test_job_files.py::test_attach_file_works_without_sqlite_returning tests/test_job_file_migration.py -q
```

Expected: attachment fails at `job_files.py` with `near "RETURNING": syntax error`; the selected migration test fails or logs a skipped upload because version insertion uses the same syntax.

### Task 2: Replace runtime RETURNING identity reads

**Files:**
- Modify: `marcedit_web/lib/job_files.py`
- Test: `tests/test_job_files.py`
- Test: `tests/test_job_file_migration.py`
- Test: `tests/test_job_file_workflow.py`

**Interfaces:**
- Produces: identical public return values from attachment, migration, export creation, and immutable version publication.

- [ ] **Step 1: Change all four runtime inserts**

At the legacy migration and attachment sites, use these exact shapes:

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

The migration uses this exact variant:

```python
cursor = conn.execute(
    "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
    "record_count,file_bytes,source_kind,label,created_by,created_at) "
    "VALUES(?,1,?,?,?,?,?,?,?)",
    (
        file_id,
        str(target),
        upload["record_count"],
        upload["file_bytes"],
        "legacy-upload",
        upload["filename"],
        upload["user_email"],
        upload["uploaded_at"],
    ),
)
version_id = int(cursor.lastrowid)
```

At export creation, retain the current `job_file_exports` SQL and tuple,
assign the cursor, then set:

```python
export_id = int(cursor.lastrowid)
```

At immutable-version publication, retain the current 12-column
`job_file_versions` SQL and tuple, assign the cursor, then set:

```python
version_id = int(cursor.lastrowid)
```

Do not issue a follow-up `SELECT`, move the read to another connection, or
change surrounding transaction/filesystem code.

- [ ] **Step 2: Prove production code contains no runtime RETURNING**

Run:

```bash
rg -n "RETURNING id" marcedit_web/lib/job_files.py
```

Expected: no output and exit 1.

- [ ] **Step 3: Run compatibility and workflow tests**

Run:

```bash
python3 -m pytest tests/test_job_files.py tests/test_job_file_migration.py tests/test_job_file_workflow.py tests/test_job_file_mutations.py -q
```

Expected: all pass; report every skip.

- [ ] **Step 4: Run static checks**

Run:

```bash
python3 -m py_compile marcedit_web/lib/job_files.py
git diff --check
```

Expected: exit 0 with no output.

- [ ] **Step 5: Commit TASK-167 implementation**

```bash
git add marcedit_web/lib/job_files.py tests/test_job_files.py tests/test_job_file_migration.py
git commit -m "fix: support production SQLite job files"
```

### Task 3: Review and record TASK-167 evidence

**Files:**
- Modify: `.tickets/TASK-167-sqlite-shared-job-attach-compatibility.md`

- [ ] **Step 1: Request independent review**

Review the TASK-167 commit range for SQLite 3.34 compatibility, same-connection `lastrowid`, transaction safety, and regression quality. Resolve every Critical and Important finding and rerun affected tests.

- [ ] **Step 2: Record exact evidence and complete the ticket**

Append exact RED/GREEN commands, pass/skip counts, static results, commit hashes, and review verdict. Set `Status: Completed` only after the review is clean.

- [ ] **Step 3: Commit evidence**

```bash
git add .tickets/TASK-167-sqlite-shared-job-attach-compatibility.md
git commit -m "docs: complete TASK-167 evidence"
```
