# Durable Operation Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Ticket: [TASK-156](../../../.tickets/TASK-156-durable-operation-queue.md)

Design: [TASK-156 durable operation queue design](../specs/2026-07-16-durable-operation-queue-design.md)

**Goal:** Run saved-task transformations through a durable, cancellable, observable SQLite queue that survives browser and service restarts without publishing partial MARC output.

**Architecture:** The private Streamlit application submits immutable operation definitions and monitors them; a separate single-operation worker claims rows through SQLite leases and processes MARC input in 5,000-record sandbox chunks. Result adoption remains a separate atomic Job-version action, while Quick Load results stay reopenable until their 30-day artifact expiry.

**Tech Stack:** Python 3.9, SQLite/WAL, pymarc 5, Streamlit 1.37+, POSIX subprocess process groups, pytest 8, systemd, Docker Compose.

## Global Constraints

- TASK-156 is the sole ticket for every change in this plan. Update its status to `In-Progress` when the implementation worktree is created and to `Completed` only after all tests and final code review pass.
- Use `superpowers:using-git-worktrees` before implementation. Preserve unrelated files in the user's main checkout.
- Use TDD for every behavior: failing intent test, observed failure, minimum implementation, passing focused test, then commit.
- Python remains `>=3.9,<3.10`; do not use syntax or stdlib APIs introduced in Python 3.10.
- Use stdlib SQLite and the existing connection-per-call/WAL conventions. Do not add Redis, Celery, RabbitMQ, SQLAlchemy, or another broker/ORM.
- The first release runs one queued operation at a time.
- Default chunk size is exactly 5,000 records and is configurable through `MARCEDIT_WEB_QUEUE_CHUNK_RECORDS` as a positive integer.
- The existing 300-second sandbox limit applies to each chunk. The overall queued operation has no five-minute limit.
- Worker interruption discards the unpublished attempt and restarts the operation from immutable input; no record checkpoint resume is added.
- Failed, cancelled, timed-out, stale-lease, or malformed attempts never expose partial output.
- Exact error totals are retained; representative error rows remain bounded by `sandbox.MAX_RETAINED_ERRORS`.
- Quick Load inputs/results and unapplied Job candidates expire after 30 days by default through `MARCEDIT_WEB_OPERATION_RETENTION_DAYS`; operation metadata and applied Job versions do not expire.
- The public tier must not register Operations, submit work, query queue state, or expose notifications/artifacts.
- Logs must not contain MARC contents, full task bodies, OAuth data, proxy secrets, or credentials.
- Use the existing Material icon convention for Notifications and Account; do not add emoji or custom icon assets.
- Stop after each task for the subagent-driven two-stage review and commit checkpoint. Execute tasks in order, one at a time.

## File Structure

### New focused modules

- `marcedit_web/lib/operations.py` — queue rows, events, errors, artifacts, leases, cancellation, visibility, notifications, and worker health.
- `marcedit_web/lib/operation_submission.py` — immutable task snapshots and Job/Quick Load source capture.
- `marcedit_web/lib/operation_runner.py` — deterministic MARC chunking, sandbox orchestration, aggregate validation, and progress.
- `marcedit_web/lib/operation_results.py` — Job apply/rollback and Quick Load reopen actions.
- `marcedit_web/ops/worker.py` — single-operation polling loop, signal handling, recovery, cleanup, and structured logs.
- `marcedit_web/render/operations.py` — Operations page rendering and user actions.
- `marcedit_web/render/operation_notifications.py` — header bell, first-return notices, and sidebar summary.
- `marcedit_web/views/D_Operations.py` — thin private-page shim.
- `deploy/marcedit-web-worker.service` — hardened production worker unit.

### New tests

- `tests/test_operation_schema.py`
- `tests/test_operations.py`
- `tests/test_operation_submission.py`
- `tests/test_operation_runner.py`
- `tests/test_operation_worker.py`
- `tests/test_operation_results.py`
- `tests/test_operations_render.py`
- `tests/test_operation_notifications.py`
- `tests/test_operation_queue_integration.py`

### Existing files changed only at their queue integration points

- `marcedit_web/lib/db.py` — additive schema version 13 migration.
- `marcedit_web/lib/sandbox.py` — progress sidecar and cancellable `Popen` lifecycle while preserving existing callers.
- `marcedit_web/lib/session.py` — reopen a retained Quick Load result by path.
- `marcedit_web/render/tasks.py` — replace saved-task synchronous execution with durable submission.
- `marcedit_web/render/__init__.py` — compact operation status in the shared sidebar.
- `marcedit_web/App.py` — private Operations page plus notification controls.
- `tests/conftest.py` — isolate the operation artifact root.
- Existing sandbox, Tasks, App navigation, session, Job-file mutation, Compose, and deployment contract tests — update only assertions affected by the queue.
- `docker-compose.yml`, `deploy/marcedit.sudoers`, `scripts/install.sh`, `scripts/deploy.sh`, `scripts/preflight-check.sh`, and `docs/deployment.md` — worker deployment and verification.

---

### Task 1: Add the durable queue schema and read model

**Files:**
- Modify: `.tickets/TASK-156-durable-operation-queue.md`
- Modify: `marcedit_web/lib/db.py`
- Create: `marcedit_web/lib/operations.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_operation_schema.py`
- Create: `tests/test_operations.py`

**Interfaces:**
- Consumes: `db.connect()`, `db.init_schema()`, and the existing `_utc_now_iso()` convention.
- Produces: `OperationError`, `operations_root() -> Path`, `get_operation(operation_id: int) -> dict`, `list_visible_operations(user_email: str) -> list[dict]`, `list_artifacts(operation_id: int, user_email: str) -> list[dict]`, `input_artifact(operation_id: int) -> dict`, `list_events(operation_id: int, user_email: str) -> list[dict]`, `list_errors(operation_id: int, user_email: str) -> list[dict]`, and internal row/event helpers used by later tasks.

- [ ] **Step 1: Create the isolated worktree and mark the ticket In-Progress**

Run the `superpowers:using-git-worktrees` skill, then change only the ticket status line:

```markdown
Status: In-Progress
```

Run: `git diff --check -- .tickets/TASK-156-durable-operation-queue.md`

Expected: exit 0 and no output.

- [ ] **Step 2: Write failing schema and read-model tests**

Add tests that assert schema version 13, exact tables, state constraints, indexes, default artifact root isolation, visibility, event ordering, and bounded error reads. The core assertions must include:

```python
def test_v13_adds_durable_operation_tables():
    db.init_schema()
    with db.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version = conn.execute(
            "SELECT version FROM _schema_version"
        ).fetchone()["version"]
    assert version == 13
    assert {
        "operations",
        "operation_artifacts",
        "operation_events",
        "operation_errors",
        "queue_worker_status",
    }.issubset(tables)


def test_public_read_model_hides_unrelated_quick_load_operation(
    queued_operation,
):
    visible = operations.list_visible_operations("other@smith.edu")
    assert queued_operation["id"] not in {row["id"] for row in visible}
```

Update `tests/conftest.py` so every test sets:

```python
monkeypatch.setenv(
    "MARCEDIT_WEB_OPERATIONS_ROOT",
    str(tmp_path / "operations"),
)
```

- [ ] **Step 3: Run tests and verify the intended failure**

Run: `pytest tests/test_operation_schema.py tests/test_operations.py -q`

Expected: FAIL because schema version 13 and `marcedit_web.lib.operations` do not exist.

- [ ] **Step 4: Implement schema version 13 and the read model**

Set `SCHEMA_VERSION = 13`, call `_migrate_to_v13(conn)` when the stored version is below 13, and create the following constrained tables and indexes:

```sql
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('saved-task-run')),
    request_version INTEGER NOT NULL DEFAULT 1 CHECK(request_version = 1),
    submitted_by TEXT NOT NULL,
    job_id INTEGER REFERENCES jobs(id),
    job_file_id INTEGER REFERENCES job_files(id),
    source_version_id INTEGER REFERENCES job_file_versions(id),
    state TEXT NOT NULL CHECK(state IN
      ('queued','running','cancelling','completed','failed','cancelled')),
    phase TEXT NOT NULL DEFAULT 'queued',
    request_json TEXT NOT NULL,
    processed_records INTEGER NOT NULL DEFAULT 0 CHECK(processed_records >= 0),
    total_records INTEGER NOT NULL CHECK(total_records >= 0),
    output_records INTEGER CHECK(output_records >= 0),
    changed_records INTEGER CHECK(changed_records >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK(error_count >= 0),
    summary_json TEXT NOT NULL DEFAULT '{}',
    terminal_message TEXT NOT NULL DEFAULT '',
    attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
    lease_owner TEXT,
    lease_token TEXT,
    lease_heartbeat_at TEXT,
    lease_expires_at TEXT,
    cancel_requested_by TEXT,
    cancel_requested_at TEXT,
    submitted_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    notification_ack_at TEXT,
    artifacts_expire_at TEXT,
    applied_version_id INTEGER REFERENCES job_file_versions(id),
    applied_by TEXT,
    applied_at TEXT,
    rolled_back_version_id INTEGER REFERENCES job_file_versions(id),
    rolled_back_by TEXT,
    rolled_back_at TEXT
);
CREATE TABLE IF NOT EXISTS operation_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('input','result')),
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    record_count INTEGER NOT NULL CHECK(record_count >= 0),
    file_bytes INTEGER NOT NULL CHECK(file_bytes >= 0),
    queue_owned INTEGER NOT NULL CHECK(queue_owned IN (0,1)),
    source_version_id INTEGER REFERENCES job_file_versions(id),
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS operation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    actor_email TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    record_index INTEGER NOT NULL CHECK(record_index >= 0),
    code TEXT NOT NULL,
    task_name TEXT,
    message TEXT NOT NULL,
    UNIQUE(operation_id, ordinal)
);
CREATE TABLE IF NOT EXISTS queue_worker_status (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    worker_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    software_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    current_operation_id INTEGER REFERENCES operations(id)
);
CREATE INDEX IF NOT EXISTS idx_operations_state_submitted
  ON operations(state, submitted_at, id);
CREATE INDEX IF NOT EXISTS idx_operations_submitter
  ON operations(submitted_by, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_operations_job
  ON operations(job_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_operation_events_operation
  ON operation_events(operation_id, id);
CREATE INDEX IF NOT EXISTS idx_operation_errors_operation
  ON operation_errors(operation_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_operation_artifacts_operation
  ON operation_artifacts(operation_id, role);
```

Implement `operations.py` with one conversion boundary and access predicate:

```python
class OperationError(ValueError):
    """Raised when an operation action is missing or unauthorized."""


def operations_root() -> Path:
    return Path(
        os.environ.get("MARCEDIT_WEB_OPERATIONS_ROOT", "data/operations")
    )


def get_operation(operation_id: int) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id,)
        ).fetchone()
    if row is None:
        raise OperationError("operation not found")
    return _dict(row)
```

`list_visible_operations` must return Quick Load rows only to `submitted_by` and
Job rows only when `job_access` currently contains the user. Task 3 extends the
read model so an approved application admin can see operation metadata and
diagnostics needed to exercise the approved cancel-any permission; artifact
download and result actions still require source access. Events and errors must
call the same visibility predicate before returning rows.

- [ ] **Step 5: Run focused schema and read-model tests**

Run: `pytest tests/test_operation_schema.py tests/test_operations.py tests/test_db.py tests/test_db_migration.py tests/test_job_schema.py -q`

Expected: PASS with no skipped tests.

- [ ] **Step 6: Commit Task 1**

```bash
git add .tickets/TASK-156-durable-operation-queue.md marcedit_web/lib/db.py marcedit_web/lib/operations.py tests/conftest.py tests/test_operation_schema.py tests/test_operations.py
git commit -m "feat: add durable operation queue schema"
```

---

### Task 2: Capture immutable saved-task submissions and input artifacts

**Files:**
- Create: `marcedit_web/lib/operation_submission.py`
- Modify: `marcedit_web/lib/operations.py`
- Create: `tests/test_operation_submission.py`
- Modify: `tests/test_operations.py`

**Interfaces:**
- Consumes: `sandbox.TaskSpec`, `job_files.get_file`, `job_files.get_version`, `operations.operations_root`, and the Task 1 schema.
- Produces: `submit_job_task_run(*, user_email: str, file_id: int, source_version_id: int, task_specs: Sequence[sandbox.TaskSpec]) -> dict` and `submit_quick_load_task_run(*, user_email: str, source_path: Path, filename: str, record_count: int, task_specs: Sequence[sandbox.TaskSpec]) -> dict`.

- [ ] **Step 1: Write failing immutable-submission tests**

Cover ordered snapshots, later task mutation, Job access, exact source version,
Quick Load durable copy, empty task rejection, unreadable source rejection, and
cleanup when the insert fails. Include:

```python
def test_quick_load_submission_snapshots_order_and_copies_input(tmp_path):
    source = tmp_path / "vendor.mrc"
    source.write_bytes(sample_mrc_bytes())
    created = operation_submission.submit_quick_load_task_run(
        user_email="owner@smith.edu",
        source_path=source,
        filename="vendor.mrc",
        record_count=2,
        task_specs=[
            sandbox.TaskSpec(name="first", body="record['001'].data = '1'"),
            sandbox.TaskSpec(name="second", body="record['001'].data += '2'"),
        ],
    )
    source.write_bytes(b"changed after submission")
    request = json.loads(created["request_json"])
    artifact = operations.input_artifact(created["id"])
    assert [task["name"] for task in request["tasks"]] == ["first", "second"]
    assert Path(artifact["file_path"]).read_bytes() == sample_mrc_bytes()
    assert artifact["queue_owned"] == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_operation_submission.py -q`

Expected: FAIL because `operation_submission` and submission functions do not exist.

- [ ] **Step 3: Implement atomic submission services**

Use this exact request shape:

```python
def _request_payload(task_specs: Sequence[sandbox.TaskSpec]) -> dict[str, Any]:
    if not task_specs:
        raise operations.OperationError("select at least one task")
    return {
        "version": 1,
        "tasks": [
            {
                "name": spec.name,
                "body": spec.body,
                "imports": list(spec.imports),
            }
            for spec in task_specs
        ],
    }
```

Quick Load submission copies to
`operations_root()/pending/<uuid>.mrc`, validates size and record count, opens
`BEGIN IMMEDIATE`, inserts `operations`, moves the file to
`operations_root()/str(operation_id)/input.mrc`, inserts the input artifact,
records `submitted`, and commits. On any exception, delete only files created by
this call.

Job submission verifies owner/editor access with `jobs.require_role`, loads the
exact `job_files.get_version`, checks that the version belongs to the file,
references its immutable path with `queue_owned=0`, and stores Job, Job-file,
and source-version ids. It does not require checkout because submission creates
an unapplied candidate and does not mutate the file; Task 7 requires checkout
and an exact current-version match before apply.

Set `artifacts_expire_at` and queue-owned artifact `expires_at` using:

```python
def retention_days() -> int:
    raw = os.environ.get("MARCEDIT_WEB_OPERATION_RETENTION_DAYS", "30")
    try:
        days = int(raw)
    except ValueError as exc:
        raise operations.OperationError(
            "MARCEDIT_WEB_OPERATION_RETENTION_DAYS must be a positive integer"
        ) from exc
    if days <= 0:
        raise operations.OperationError(
            "MARCEDIT_WEB_OPERATION_RETENTION_DAYS must be a positive integer"
        )
    return days
```

- [ ] **Step 4: Run focused submission tests**

Run: `pytest tests/test_operation_submission.py tests/test_operations.py tests/test_job_files.py -q`

Expected: PASS with no skipped tests.

- [ ] **Step 5: Commit Task 2**

```bash
git add marcedit_web/lib/operation_submission.py marcedit_web/lib/operations.py tests/test_operation_submission.py tests/test_operations.py
git commit -m "feat: persist immutable queued task submissions"
```

---

### Task 3: Implement leases, state transitions, cancellation, and worker health

**Files:**
- Modify: `marcedit_web/lib/operations.py`
- Modify: `tests/test_operations.py`

**Interfaces:**
- Consumes: Task 1 operation rows/events and Task 2 queued submissions.
- Produces: immutable `Lease(operation_id: int, token: str, attempt: int, request: dict, input_artifact: dict)`, `claim_next`, `renew_lease`, `request_cancel`, `is_cancel_requested`, `finish_cancelled`, `fail_operation`, `complete_operation`, `recover_expired`, `heartbeat_worker`, `worker_health`, and `acknowledge_notification`.

- [ ] **Step 1: Write failing lifecycle and race tests**

Test oldest-first claim, two-thread contention, token mismatch, renewal, queued
cancel, running cancel, submitter/Job owner/admin permissions, editor/viewer
denial, completion-versus-cancel transaction ordering, expired-running requeue,
expired-cancelling cancellation, notification acknowledgement, and health
staleness. The race contract must be explicit:

```python
def test_cancel_wins_before_completion_transaction(queued_operation, candidate):
    lease = operations.claim_next("worker-a", lease_seconds=30)
    cancelled = operations.request_cancel(
        queued_operation["id"], by="owner@smith.edu"
    )
    assert cancelled["state"] == "cancelling"
    with pytest.raises(
        operations.OperationError,
        match="operation is no longer running",
    ):
        operations.complete_operation(
            lease,
            result_path=candidate,
            output_records=1,
            changed_records=1,
            error_count=0,
            errors=[],
            summary={},
        )
```

- [ ] **Step 2: Run lifecycle tests and verify failure**

Run: `pytest tests/test_operations.py -q`

Expected: FAIL on missing lease and lifecycle interfaces.

- [ ] **Step 3: Implement transaction-guarded lifecycle methods**

Define:

```python
@dataclass(frozen=True)
class Lease:
    operation_id: int
    token: str
    attempt: int
    request: dict[str, Any]
    input_artifact: dict[str, Any]


def claim_next(worker_id: str, *, lease_seconds: int = 30) -> Lease | None:
    if lease_seconds <= 0:
        raise OperationError("lease_seconds must be positive")
```

`claim_next` must use `BEGIN IMMEDIATE`, select the oldest `queued` row, update
it with `WHERE id=? AND state='queued'`, increment `attempt`, set a UUID token,
set `started_at=COALESCE(started_at, now)`, append `claimed`, and return the
request plus input artifact from the same transaction.

Every lease-owned mutation must use a predicate containing the operation ID,
current lease token, and lifecycle-appropriate state. Running mutations use:

```sql
WHERE id=? AND state='running' AND lease_token=?
```

`finish_cancelled` runs after cancellation has transitioned the operation and
therefore requires `WHERE id=? AND state='cancelling' AND lease_token=?`.

`complete_operation` adds `AND cancel_requested_at IS NULL`, validates and
moves the owned result into the operation result path before inserting the
artifact, and rolls the move back to the attempt path if the SQLite transaction
fails. It stores only the first `sandbox.MAX_RETAINED_ERRORS` rows while keeping
the exact `error_count`.

`request_cancel` authorizes submitter, current Job owner, or approved application
admin. Queued transitions directly to `cancelled`; running transitions to
`cancelling`; terminal states raise `OperationError("operation is already finished")`.

`recover_expired` requeues expired `running` rows after clearing lease fields and
resetting processed records to zero. It directly cancels expired `cancelling`
rows. Each transition appends exactly one event.

`heartbeat_worker` upserts singleton row 1. `worker_health(max_age_seconds=15)`
returns `{"available": bool, "row": dict | None}` based on the stored UTC
heartbeat, not process inspection.

- [ ] **Step 4: Run lifecycle, concurrency, and DB tests**

Run: `pytest tests/test_operations.py tests/test_operation_schema.py tests/test_db.py -q`

Expected: PASS with no skipped tests.

- [ ] **Step 5: Commit Task 3**

```bash
git add marcedit_web/lib/operations.py tests/test_operations.py
git commit -m "feat: add queued operation lifecycle controls"
```

---

### Task 4: Make the sandbox report progress and support safe cancellation

**Files:**
- Modify: `marcedit_web/lib/sandbox.py`
- Modify: `tests/test_sandbox.py`

**Interfaces:**
- Consumes: existing `TaskSpec`, `SandboxResult`, resource limits, error cap, and 300-second default.
- Produces: backward-compatible `run_tasks_subprocess` with new keyword-only `progress_path: Path | None`, `progress_callback: Callable[[int], None] | None`, `cancel_requested: Callable[[], bool] | None`, and `poll_interval: float = 0.25`; also produces `SandboxResult.cancelled: bool`.

- [ ] **Step 1: Write failing progress and process-group cancellation tests**

Preserve every existing timeout/resource/error assertion and add:

```python
def test_progress_sidecar_reaches_input_count(tmp_path, two_record_bytes):
    progress = tmp_path / "progress.json"
    observed = []
    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        two_record_bytes,
        progress_path=progress,
        progress_callback=observed.append,
    )
    assert result.cancelled is False
    assert json.loads(progress.read_text())["processed_records"] == 2
    assert observed[-1] == 2


def test_cancellation_terminates_sandbox_process_group(tmp_path, record_bytes):
    checks = iter([False, True])
    result = run_tasks_subprocess(
        [TaskSpec(name="slow", body="while True: pass")],
        record_bytes,
        timeout=30,
        tmp_dir=tmp_path,
        cancel_requested=lambda: next(checks, True),
        poll_interval=0.01,
    )
    assert result.cancelled is True
    assert result.timed_out is False
```

- [ ] **Step 2: Run sandbox tests and verify failure**

Run: `pytest tests/test_sandbox.py -q`

Expected: FAIL because progress/cancellation parameters and `cancelled` do not exist.

- [ ] **Step 3: Add child progress writes and parent polling**

Extend the child arguments with `--progress`. After each input record, atomically
replace the progress JSON so the parent never reads a partial document:

```python
def _write_progress(path, processed_records):
    if not path:
        return
    temporary = path + ".tmp"
    with open(temporary, "w") as progress_file:
        json.dump({"processed_records": processed_records}, progress_file)
    os.replace(temporary, path)
```

Replace the blocking parent call with `subprocess.Popen` using
`start_new_session=True` and a `communicate(timeout=poll_interval)` loop. Track
elapsed time with `time.monotonic()`. On each poll, read a valid changed progress
sidecar value and call `progress_callback(processed_records)` once for that new
value. When cancellation is requested, call
`os.killpg(process.pid, signal.SIGTERM)`, wait up to two seconds, then call
`SIGKILL` if still alive. Use the same process-group termination path for elapsed
timeout. Preserve exact CPU soft/hard limits and existing timeout normalization.

Return:

```python
return SandboxResult(
    output_path=output_path,
    errors=errors,
    error_count=error_count,
    stderr=stderr,
    returncode=returncode,
    timed_out=timed_out,
    cancelled=cancelled,
)
```

Do not add a nonzero-exit error when `cancelled` is true.

- [ ] **Step 4: Run all sandbox and saved-task compatibility tests**

Run: `pytest tests/test_sandbox.py tests/test_tasks_export.py tests/test_batch_replace.py tests/test_codegen_safety.py -q`

Expected: PASS; POSIX-only skips must be reported by pytest and not described as coverage.

- [ ] **Step 5: Commit Task 4**

```bash
git add marcedit_web/lib/sandbox.py tests/test_sandbox.py tests/test_tasks_export.py
git commit -m "feat: add cancellable sandbox progress"
```

---

### Task 5: Build the deterministic chunked MARC runner

**Files:**
- Create: `marcedit_web/lib/operation_runner.py`
- Modify: `marcedit_web/lib/operations.py`
- Create: `tests/test_operation_runner.py`

**Interfaces:**
- Consumes: `operations.Lease`, Task 4 cancellable sandbox, `RecordStore`, `task_diff.compute_task_diff`, and lease/progress methods.
- Produces: `OperationCancelled`, `OperationRunError(code: str, message: str)`, `RunOutcome`, `queue_chunk_records() -> int`, and `run_saved_task_operation(lease: operations.Lease, *, chunk_size: int | None = None) -> RunOutcome`.

- [ ] **Step 1: Write failing chunk runner tests**

Test a 12-record input with chunk size 5 creates three sandbox calls, task order
matches a one-shot run, progress is monotonic, error indices gain the chunk
offset, cancellation discards the aggregate, chunk timeout fails, malformed or
cardinality-changing output fails, and a 300-second limit is passed to every
chunk rather than to the whole runner.

```python
def test_chunk_errors_use_input_wide_indices(lease, monkeypatch):
    monkeypatch.setattr(operation_runner, "queue_chunk_records", lambda: 5)
    outcome = operation_runner.run_saved_task_operation(lease)
    assert outcome.error_count == 2
    assert [error["index"] for error in outcome.errors] == [3, 8]
```

- [ ] **Step 2: Run runner tests and verify failure**

Run: `pytest tests/test_operation_runner.py -q`

Expected: FAIL because `operation_runner` does not exist.

- [ ] **Step 3: Implement streaming chunks, aggregate validation, and progress**

Validate configuration exactly:

```python
def queue_chunk_records() -> int:
    raw = os.environ.get("MARCEDIT_WEB_QUEUE_CHUNK_RECORDS", "5000")
    try:
        size = int(raw)
    except ValueError as exc:
        raise operations.OperationError(
            "MARCEDIT_WEB_QUEUE_CHUNK_RECORDS must be a positive integer"
        ) from exc
    if size <= 0:
        raise operations.OperationError(
            "MARCEDIT_WEB_QUEUE_CHUNK_RECORDS must be a positive integer"
        )
    return size
```

Parse `lease.request["tasks"]` into `sandbox.TaskSpec` values. Stream the input
through `pymarc.MARCReader`, write no more than `chunk_size` records to each
chunk input, and fail on a `None` record. For each chunk:

1. set phase `processing` and renew the lease;
2. invoke `sandbox.run_tasks_subprocess` with `timeout=300`, a progress sidecar,
   a progress callback that stores `completed_before_chunk + current_chunk`, and
   a cancellation callback that also renews the lease;
3. reject cancelled, timed-out, nonzero, malformed, or cardinality-mismatched
   output;
4. translate every retained error index by `completed_before_chunk`;
5. append valid chunk bytes to the attempt aggregate; and
6. update durable progress to the completed chunk boundary.

After the last chunk, set phase `validating`, require the aggregate
`RecordStore` count and full iteration count to equal the input total, compute
the diff summary, and return an immutable outcome:

```python
class OperationCancelled(RuntimeError):
    """Raised after a requested cancellation stops the sandbox child."""


class OperationRunError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RunOutcome:
    candidate_path: Path
    input_records: int
    output_records: int
    changed_records: int
    error_count: int
    errors: tuple[dict[str, Any], ...]
    summary: dict[str, Any]
```

On every exception, remove the attempt directory only after preserving enough
context for the worker log; never create a result artifact here.

- [ ] **Step 4: Run runner and sandbox tests**

Run: `pytest tests/test_operation_runner.py tests/test_operations.py tests/test_sandbox.py tests/test_task_diff.py -q`

Expected: PASS with only documented platform skips.

- [ ] **Step 5: Commit Task 5**

```bash
git add marcedit_web/lib/operation_runner.py marcedit_web/lib/operations.py tests/test_operation_runner.py
git commit -m "feat: process queued tasks in bounded chunks"
```

---

### Task 6: Add the durable worker, restart recovery, and artifact cleanup

**Files:**
- Create: `marcedit_web/ops/worker.py`
- Modify: `marcedit_web/lib/operations.py`
- Create: `tests/test_operation_worker.py`

**Interfaces:**
- Consumes: Tasks 3 and 5 claim/runner/completion APIs.
- Produces: `run_once(worker_id: str) -> bool`, `run_forever(worker_id: str | None = None, poll_seconds: float = 1.0) -> int`, `operations.cleanup_expired_artifacts(now: datetime | None = None) -> int`, worker CLI `python -m marcedit_web.ops.worker`, and heartbeat probe `python -m marcedit_web.ops.worker --check`.

- [ ] **Step 1: Write failing worker, restart, cleanup, and logging tests**

Cover idle heartbeat and `--check` exit status, one claim per `run_once`, completion, warning completion,
expected failure, unexpected exception with stack trace, SIGTERM exit after the
current control checkpoint, expired lease recovery, 30-day cleanup, preservation
of metadata, preservation of `queue_owned=0` Job paths, and log redaction.

```python
def test_worker_restart_requeues_and_restarts_from_zero(running_operation):
    with db.connect() as conn:
        conn.execute(
            "UPDATE operations SET lease_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00Z", running_operation["id"]),
        )
    worker.run_once("replacement-worker")
    events = operations.list_events(
        running_operation["id"], "owner@smith.edu"
    )
    assert any(event["kind"] == "recovered" for event in events)
    assert operations.get_operation(running_operation["id"])["attempt"] == 2
```

- [ ] **Step 2: Run worker tests and verify failure**

Run: `pytest tests/test_operation_worker.py -q`

Expected: FAIL because the worker module does not exist.

- [ ] **Step 3: Implement one-operation polling and safe cleanup**

Use `logging.getLogger("marcedit_web.operation_worker")`. `run_once` must:

```python
def run_once(worker_id: str) -> bool:
    operations.heartbeat_worker(worker_id, current_operation_id=None)
    operations.recover_expired()
    lease = operations.claim_next(worker_id)
    if lease is None:
        return False
    operations.heartbeat_worker(
        worker_id,
        current_operation_id=lease.operation_id,
    )
    try:
        outcome = operation_runner.run_saved_task_operation(lease)
        operations.complete_operation(
            lease,
            result_path=outcome.candidate_path,
            output_records=outcome.output_records,
            changed_records=outcome.changed_records,
            error_count=outcome.error_count,
            errors=list(outcome.errors),
            summary=outcome.summary,
        )
    except operation_runner.OperationCancelled:
        operations.finish_cancelled(lease)
    except operation_runner.OperationRunError as exc:
        operations.fail_operation(lease, code=exc.code, message=str(exc))
    except Exception as exc:
        logger.exception(
            "queued operation failed operation_id=%s attempt=%s",
            lease.operation_id,
            lease.attempt,
        )
        operations.fail_operation(
            lease,
            code="worker-internal-error",
            message="Processing failed because of an internal worker error.",
        )
    finally:
        operations.heartbeat_worker(worker_id, current_operation_id=None)
    return True
```

`run_forever` installs SIGTERM/SIGINT handlers that set a local stop event,
heartbeats while idle, runs artifact cleanup once at startup and then no more
than once per hour while idle, and exits 0 after the current polling/control boundary.
The sandbox cancellation/process-group logic handles user cancellation; service
termination may leave an expired lease for the replacement worker.

Cleanup deletes only expired `queue_owned=1` files that are not an applied Job
version and removes now-empty attempt directories. It retains artifact rows,
paths, expiry timestamps, operation rows, events, and errors so the UI can say
that bytes expired, then appends `artifacts-expired`. Cleanup failures log
operation/artifact ids and retry later.

The CLI `--check` path calls `operations.worker_health(max_age_seconds=15)`,
prints `ok` and exits 0 only for a fresh heartbeat, otherwise prints
`operation worker heartbeat is stale or missing` to stderr and exits 1.

- [ ] **Step 4: Run worker, lifecycle, and runner tests**

Run: `pytest tests/test_operation_worker.py tests/test_operation_runner.py tests/test_operations.py -q`

Expected: PASS with no skipped tests.

- [ ] **Step 5: Commit Task 6**

```bash
git add marcedit_web/ops/worker.py marcedit_web/lib/operations.py tests/test_operation_worker.py
git commit -m "feat: run and recover durable queued operations"
```

---

### Task 7: Add result review actions, immutable apply, and rollback

**Files:**
- Create: `marcedit_web/lib/operation_results.py`
- Modify: `marcedit_web/lib/session.py`
- Modify: `marcedit_web/lib/operations.py`
- Create: `tests/test_operation_results.py`
- Modify: `tests/test_session_restore.py`

**Interfaces:**
- Consumes: completed operation/artifact queries, `job_files.adopt_candidate`, existing checkout/version guards, and session `RecordStore` replacement.
- Produces: `apply_job_result(operation_id: int, *, user_email: str, opened_version_id: int) -> dict`, `rollback_job_result(operation_id: int, *, user_email: str, opened_version_id: int) -> dict`, `reopen_quick_load(operation_id: int, *, user_email: str, use_result: bool) -> RecordStore`, and `session.replace_current_store_from_path` reuse.

- [ ] **Step 1: Write failing result-action tests**

Cover completed-only actions, source version still current, checkout holder,
owner/editor authorization, viewer denial, result retained after apply, operation
applied fields/events, rollback as a newly numbered version from source bytes,
history preservation, Quick Load reopen result/original, expiry rejection, and
cross-user denial.

```python
def test_rollback_creates_new_version_without_erasing_applied_version(
    applied_operation,
):
    rolled_back = operation_results.rollback_job_result(
        applied_operation["id"],
        user_email=OWNER,
        opened_version_id=applied_operation["applied_version_id"],
    )
    assert rolled_back["version_number"] == 3
    assert rolled_back["parent_version_id"] == applied_operation["applied_version_id"]
    assert Path(rolled_back["file_path"]).read_bytes() == source_version_bytes()
    assert job_files.get_version(
        applied_operation["applied_version_id"], OWNER
    ) is not None
```

- [ ] **Step 2: Run result tests and verify failure**

Run: `pytest tests/test_operation_results.py tests/test_session_restore.py -q`

Expected: FAIL because result-action functions do not exist.

- [ ] **Step 3: Implement apply, rollback, and Quick Load reopen**

For apply, require completed Job operation, unexpired result, and
`opened_version_id == source_version_id`. Copy the retained result to a fresh
queue-owned apply temporary path because `job_files.adopt_candidate` consumes
its candidate. Call:

```python
created = job_files.adopt_candidate(
    file_id=int(operation["job_file_id"]),
    opened_version_id=opened_version_id,
    user_email=user_email,
    candidate_path=apply_copy,
    source_kind="queued-task",
    label=_operation_label(operation),
    summary=json.loads(operation["summary_json"]),
    validation={"error_count": operation["error_count"]},
)
```

Then atomically set `applied_version_id/by/at` only if it is still null and
append `result-applied`. The retained operation result must still exist.

For rollback, require the applied version to be the exact opened/current
version, copy the immutable `source_version_id` bytes, adopt with
`source_kind="queued-task-rollback"`, set rollback fields, and append
`result-rolled-back`. Repeated rollback attempts after a recorded rollback fail
with a clear message.

For Quick Load, require submitter ownership, completed state, unexpired selected
artifact, and call `session.replace_current_store_from_path` with a filename
that identifies original or queued result. Do not delete either artifact.

- [ ] **Step 4: Run result, Job mutation, collaboration, and session tests**

Run: `pytest tests/test_operation_results.py tests/test_job_file_mutations.py tests/test_collaboration.py tests/test_session_restore.py -q`

Expected: PASS with no skipped tests.

- [ ] **Step 5: Commit Task 7**

```bash
git add marcedit_web/lib/operation_results.py marcedit_web/lib/session.py marcedit_web/lib/operations.py tests/test_operation_results.py tests/test_session_restore.py
git commit -m "feat: apply and roll back queued results"
```

---

### Task 8: Build the private Operations page

**Files:**
- Create: `marcedit_web/render/operations.py`
- Create: `marcedit_web/views/D_Operations.py`
- Modify: `marcedit_web/App.py`
- Modify: `marcedit_web/lib/operations.py`
- Create: `tests/test_operations_render.py`
- Modify: `tests/test_app_pages.py`

**Interfaces:**
- Consumes: visible operation/event/error queries, cancel, result actions, worker health, and shared `sidebar_status`.
- Produces: `render.operations.render() -> None`, private `Operations` navigation route, status cards, progress, history, and action controls.

- [ ] **Step 1: Write failing navigation and rendering tests**

Test private registration and public exclusion; empty history; unavailable worker
with queued rows; progress fraction and phase; completed-with-errors status;
bounded details; cancellation permission; Job review/download/apply/rollback;
Quick Load download/reopen; expired-artifact copy; and event ordering.

```python
def test_public_mode_never_registers_operations(monkeypatch):
    app = _load_app(monkeypatch, "public")
    assert "Operations" not in _url_paths(app.build_pages(public=True))


def test_running_card_shows_record_progress(fake_st, running_operation):
    operations_render.render()
    assert "12,400 of 60,498" in fake_st.rendered_text
    assert fake_st.progress_values == [pytest.approx(12400 / 60498)]
```

- [ ] **Step 2: Run UI tests and verify failure**

Run: `pytest tests/test_operations_render.py tests/test_app_pages.py -q`

Expected: FAIL because the Operations route and renderer do not exist.

- [ ] **Step 3: Implement the Operations route and renderer**

Register only in `build_pages(public=False)` under Start:

```python
PageSpec(
    url_path="Operations",
    title="Operations",
    script="views/D_Operations.py",
    icon=":material/pending_actions:",
)
```

The thin page shim must initialize the session, title the page, render the shared
sidebar, and call `operations.render()`.

The renderer queries only `list_visible_operations(current_user)`. Show counts
for running, queued, needs attention (`failed` plus completed with errors), and
completed. Active cards show phase, `processed_records`, `total_records`,
percentage, elapsed time, submitter, source, and Cancel when authorized. A
queued row with stale/missing worker heartbeat displays exactly:

```text
Processing service unavailable. Your operation is safely queued and will start when the worker returns.
```

Terminal expanders show summary, exact error count, retained errors, events,
expiration, and applicable actions. Download buttons read bytes only inside the
expanded terminal row and only when the result exists. Job Apply/Rollback and
Quick Load reopen buttons call Task 7 services and surface `OperationError` or
`JobFileError` without changing operation state.

Use a Streamlit fragment with `run_every="2s"` only around active-operation
status when the installed Streamlit exposes `st.fragment`; preserve a manual
Refresh button fallback for older supported releases.

- [ ] **Step 4: Run page, history, and Job UI tests**

Run: `pytest tests/test_operations_render.py tests/test_app_pages.py tests/test_history_render.py tests/test_jobs_page.py -q`

Expected: PASS with no skipped tests.

- [ ] **Step 5: Commit Task 8**

```bash
git add marcedit_web/render/operations.py marcedit_web/views/D_Operations.py marcedit_web/App.py marcedit_web/lib/operations.py tests/test_operations_render.py tests/test_app_pages.py
git commit -m "feat: add durable operations page"
```

---

### Task 9: Queue saved-task runs and add persistent Material notifications

**Files:**
- Modify: `marcedit_web/render/tasks.py`
- Create: `marcedit_web/render/operation_notifications.py`
- Modify: `marcedit_web/render/__init__.py`
- Modify: `marcedit_web/App.py`
- Create: `tests/test_operation_notifications.py`
- Modify: `tests/test_tasks_export.py`
- Modify: `tests/test_quick_batch_render.py`

**Interfaces:**
- Consumes: Task 2 submission functions, operation notification queries/acknowledgement, Operations route, and current session Job/Quick Load context.
- Produces: saved-task Run button queues instead of blocking; `render_header_bell(user_email: str)`, `render_first_return_notice(user_email: str)`, and `render_sidebar_summary(user_email: str)`.

- [ ] **Step 1: Write failing submission and notification tests**

Test ordered selected tasks are enqueued, the tab-open warning is removed, no
sandbox runs in Streamlit, Job context captures exact version, Quick Load copies
input, success links to Operations, bell unread count, Material icons, first
return success/error notices, mark-one/all acknowledgement, cancelled-by-other
alert, no self-cancel alert, and public-mode absence.

```python
def test_run_button_queues_without_calling_sandbox(fake_st, monkeypatch):
    called = []
    monkeypatch.setattr(
        tasks_render.sandbox,
        "run_tasks_subprocess",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )
    tasks_render._submit_queued_run(["first", "second"], TASKS_DIR)
    assert called == []
    assert fake_st.successes == ["Operation queued. You can safely leave this page."]


def test_header_uses_existing_material_icon_names(fake_st):
    operation_notifications.render_header_bell("owner@smith.edu")
    assert ":material/notifications:" in fake_st.popover_icons
    assert "🔔" not in fake_st.rendered_text
```

- [ ] **Step 2: Run Tasks and notification tests and verify failure**

Run: `pytest tests/test_operation_notifications.py tests/test_tasks_export.py -q`

Expected: FAIL because saved-task runs remain synchronous and notifications do not exist.

- [ ] **Step 3: Replace synchronous saved-task submission at the UI boundary**

Retain the existing task-file parsing so submitted bodies match what users can
run. Replace the Run button target with `_submit_queued_run`. That function
builds ordered `sandbox.TaskSpec` values, then chooses exactly one source path:

```python
if _uses_job_file_versions():
    created = operation_submission.submit_job_task_run(
        user_email=user,
        file_id=int(st.session_state["job_file_id"]),
        source_version_id=int(st.session_state["job_file_version_id"]),
        task_specs=specs,
    )
else:
    created = operation_submission.submit_quick_load_task_run(
        user_email=user,
        source_path=store.path,
        filename=session.current_filename() or "quick-load.mrc",
        record_count=store.count(),
        task_specs=specs,
    )
```

Show the success copy from the test and a page link to Operations. Remove the
instruction to leave the tab open and remove the saved-task Run button's call to
`_execute_sandboxed_run`. Delete saved-task-only in-session history code that no
longer has a caller; leave quick-batch preview/apply code unchanged.

- [ ] **Step 4: Implement alerts and shared sidebar status**

Add operations query functions `list_unread_notifications`,
`acknowledge_notification`, and `acknowledge_all_notifications`. Notifications
are terminal submitter-owned rows where `notification_ack_at IS NULL`, excluding
self-cancelled operations.

In the existing authenticated header container, render the bell only when
`runmode.is_private()` is true and `authz.get_user(email)` reports
`status == "approved"`; this keeps the
pre-access-gate Account/sign-out behavior intact for pending and revoked users.
Render a popover immediately before Account with
`icon=":material/notifications:"` and label
`Notifications (N)`. Use matching Streamlit control styling rather than injected
icon CSS. Each alert has View operation and Mark read; include Mark all read.

After `access_gate.enforce_access()` and before navigation, render the newest
unseen terminal alert once per browser session with success, warning, or error
copy; the durable unread row remains until acknowledged. Add a compact sidebar
line and Operations page link for queued/running/attention counts. Guard both
the first-return call and the shared-sidebar queue query with
`runmode.is_private()` so public pages never open the catalog database.

- [ ] **Step 5: Run Tasks, notifications, navigation, and public-mode tests**

Run: `pytest tests/test_operation_notifications.py tests/test_tasks_export.py tests/test_quick_batch_render.py tests/test_app_pages.py tests/test_runmode.py -q`

Expected: PASS with no skipped tests.

- [ ] **Step 6: Commit Task 9**

```bash
git add marcedit_web/render/tasks.py marcedit_web/render/operation_notifications.py marcedit_web/render/__init__.py marcedit_web/App.py marcedit_web/lib/operations.py tests/test_operation_notifications.py tests/test_tasks_export.py tests/test_quick_batch_render.py tests/test_app_pages.py
git commit -m "feat: queue saved tasks with persistent alerts"
```

---

### Task 10: Deploy and monitor the worker in systemd and Compose

**Files:**
- Create: `deploy/marcedit-web-worker.service`
- Modify: `docker-compose.yml`
- Modify: `deploy/marcedit.sudoers`
- Modify: `scripts/install.sh`
- Modify: `scripts/deploy.sh`
- Modify: `scripts/preflight-check.sh`
- Modify: `docs/deployment.md`
- Modify: `tests/test_deploy_units.py`
- Modify: `tests/test_docker_compose_config.py`

**Interfaces:**
- Consumes: `python -m marcedit_web.ops.worker`, shared SQLite/data paths, worker heartbeat, and existing private-service hardening.
- Produces: enabled worker service, Compose worker, ordered deployment restart, preflight checks, and operator journal/status instructions.

- [ ] **Step 1: Write failing deployment contract tests**

Assert the worker unit uses the private environment/database, same service user,
`ReadWritePaths` data access, no network port, restart policy, and worker CLI;
Compose shares image/data/source without ports; deploy stops worker before code
update, starts app/readiness before worker, and checks heartbeat; public unit is
unchanged.

```python
def test_worker_systemd_unit_is_hardened_and_uses_private_data():
    unit = _repo_file("deploy/marcedit-web-worker.service")
    assert "User=marcedit" in unit
    assert "EnvironmentFile=/var/www/html/marcedit-web/.env" in unit
    assert "MARCEDIT_WEB_DB_PATH=/var/www/html/marcedit-web/data/marcedit.db" in unit
    assert "ExecStart=/var/www/html/marcedit-web/.venv/bin/python -m marcedit_web.ops.worker" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ReadWritePaths=/var/www/html/marcedit-web/data" in unit
    assert "--server.port" not in unit


def test_compose_worker_shares_data_without_publishing_port():
    compose = Path("docker-compose.yml").read_text()
    worker = compose.split("  marcedit-web-worker:", 1)[1]
    assert "- ./data:/app/data" in worker
    assert "python -m marcedit_web.ops.worker" in worker
    assert "condition: service_healthy" in worker
    assert "ports:" not in worker
```

- [ ] **Step 2: Run deployment tests and verify failure**

Run: `pytest tests/test_deploy_units.py tests/test_docker_compose_config.py -q`

Expected: FAIL because the worker unit and Compose service do not exist.

- [ ] **Step 3: Add worker deployment artifacts and safe rollout order**

Create a service with these active directives:

```ini
[Unit]
Description=marcedit-web durable operation worker
Documentation=https://github.com/smith-libraries/marcedit-web
After=network.target

[Service]
Type=simple
User=marcedit
Group=marcedit
WorkingDirectory=/var/www/html/marcedit-web
EnvironmentFile=/var/www/html/marcedit-web/.env
Environment=MARCEDIT_WEB_MODE=private
Environment=MARCEDIT_WEB_PROD=1
Environment=MARCEDIT_WEB_DB_PATH=/var/www/html/marcedit-web/data/marcedit.db
ExecStartPre=/var/www/html/marcedit-web/.venv/bin/python -m marcedit_web.ops.health
ExecStart=/var/www/html/marcedit-web/.venv/bin/python -m marcedit_web.ops.worker
Restart=on-failure
RestartSec=5
MemoryHigh=1536M
MemoryMax=2G
CPUQuota=200%
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/www/html/marcedit-web/data

[Install]
WantedBy=multi-user.target
```

Add Compose `marcedit-web-worker` with the same build/image, source/data/config
mounts, environment, and restart policy as the app, an explicit worker command,
no `ports` key, and `depends_on` the Streamlit service with
`condition: service_healthy`. The dependency orders initial schema creation but
does not couple later Streamlit restarts to the running worker.

Update install and sudoers for enable/start/stop/restart of the worker. Update
deploy order to stop worker, pull/install, restart private app and pass readiness,
then start worker and verify a fresh heartbeat through a CLI check. The script
must fail loud and name both journal units on failure.

Document status, logs, cancellation/recovery behavior during deploy, environment
settings, 30-day cleanup, backup inclusion of `data/operations`, and worker
heartbeat diagnosis. Extend preflight to verify unit presence, writable
operations root, and the configured positive integers.

- [ ] **Step 4: Run contract and syntax verification**

Run: `pytest tests/test_deploy_units.py tests/test_docker_compose_config.py tests/test_ops_health.py -q`

Expected: PASS; tests that intentionally skip absent build-context files must be reported.

Run: `docker compose config --quiet`

Expected: exit 0 and no output.

Run when `systemd-analyze` is installed: `systemd-analyze verify deploy/marcedit-web-worker.service`

Expected: exit 0; environment-specific warnings that do not invalidate the unit must be copied into the task checkpoint.

- [ ] **Step 5: Commit Task 10**

```bash
git add deploy/marcedit-web-worker.service docker-compose.yml deploy/marcedit.sudoers scripts/install.sh scripts/deploy.sh scripts/preflight-check.sh docs/deployment.md tests/test_deploy_units.py tests/test_docker_compose_config.py
git commit -m "ops: deploy durable operation worker"
```

---

### Task 11: Prove restart safety, run the full suite, review, and complete the ticket

**Files:**
- Create: `tests/test_operation_queue_integration.py`
- Modify: `scripts/benchmark-large-batch.py`
- Modify: `.tickets/TASK-156-durable-operation-queue.md`
- Modify only files identified by failing tests or code review within TASK-156 scope.

**Interfaces:**
- Consumes: the complete Tasks submission → SQLite → worker → Operations → apply/rollback flow.
- Produces: restart/cancellation/large-file evidence, final review evidence, and completed ticket status.

- [ ] **Step 1: Write failing end-to-end durability tests before any integration fixes**

Use real SQLite, real operation artifacts, and the real worker `run_once`; mock
only time/process death where a real kill would make the test nondeterministic.
Cover browser session loss, app reinitialization, worker death after at least one
chunk, stale worker completion rejection, competing worker claims, running
cancellation, no partial artifact, completion with record errors, Job apply then
rollback, and Quick Load reopen.

```python
def test_worker_restart_publishes_one_complete_result(
    submitted_operation,
    simulate_worker_loss_after_first_chunk,
):
    first_attempt = simulate_worker_loss_after_first_chunk(submitted_operation)
    assert first_attempt.published_artifacts == []
    operations.recover_expired()
    assert worker.run_once("replacement") is True
    completed = operations.get_operation(submitted_operation["id"])
    artifacts = operations.list_artifacts(
        submitted_operation["id"], "owner@smith.edu"
    )
    assert completed["state"] == "completed"
    assert completed["attempt"] == 2
    assert [artifact["role"] for artifact in artifacts].count("result") == 1
    assert RecordStore.from_path(Path(artifacts[-1]["file_path"])).count() == 12
```

- [ ] **Step 2: Run integration tests and observe any contract gap**

Run: `pytest tests/test_operation_queue_integration.py -q`

Expected before integration fixes: at least one FAIL that identifies a cross-module contract mismatch, or PASS if Tasks 1-10 already satisfy every end-to-end contract. Record the actual result in the checkpoint; do not manufacture a failure.

- [ ] **Step 3: Make only the minimum integration corrections**

For each real failure, add or tighten the narrowest assertion first, then correct
the owning module. Do not add queue support to merge, split, quick batch, batch
replace, validation fixes, or other out-of-scope workflows.

Extend `scripts/benchmark-large-batch.py` with a queued saved-task scenario that
accepts record count and chunk size, reports operation id, attempts, elapsed
time, peak RSS, processed/output/error counts, and asserts completed output
cardinality. Keep the existing direct benchmark mode available.

- [ ] **Step 4: Run focused queue verification**

Run:

```bash
pytest tests/test_operation_schema.py tests/test_operations.py tests/test_operation_submission.py tests/test_operation_runner.py tests/test_operation_worker.py tests/test_operation_results.py tests/test_operations_render.py tests/test_operation_notifications.py tests/test_operation_queue_integration.py tests/test_sandbox.py tests/test_tasks_export.py -q
```

Expected: PASS with every skip listed and explained.

- [ ] **Step 5: Run the realistic benchmark**

Run inside the development container with a generated 60,498-record input and a
test task chosen to make total elapsed processing exceed one injected short
per-chunk limit in the benchmark harness while each individual chunk remains
within its limit:

```bash
docker compose run --rm marcedit-web python scripts/benchmark-large-batch.py --queued --records 60498 --chunk-records 5000
```

Expected: terminal state `completed`, input/output count 60,498, one published
result, and more than one completed chunk. Capture elapsed time and peak RSS;
do not claim a literal five-minute CI run unless the measured run actually
exceeds five minutes.

- [ ] **Step 6: Run the complete Docker test suite**

Run:

```bash
docker compose run --rm marcedit-web pytest -q
```

Expected: all tests pass. Report the exact pass and skip counts; any skip remains
visible and is not described as passing coverage.

- [ ] **Step 7: Request final independent code review**

Use `superpowers:requesting-code-review` against the full TASK-156 commit range.
The reviewer must check spec coverage, cancellation/completion races, stale
leases, filesystem/SQLite failure windows, permissions, public-tier isolation,
log redaction, cleanup ownership, UI copy, deployment ordering, and test intent.

If findings exist, address them with TDD in the owning task's files, rerun that
task's focused tests, then rerun Steps 4 and 6. Repeat review until no blocking
or important findings remain.

- [ ] **Step 8: Mark the ticket Completed and commit the final evidence checkpoint**

Only after Steps 4-7 succeed, change:

```markdown
Status: Completed
```

Run: `git diff --check`

Expected: exit 0 and no output.

Commit the integration test, benchmark extension, ticket status, and reviewed
corrections:

```bash
git add tests/test_operation_queue_integration.py scripts/benchmark-large-batch.py .tickets/TASK-156-durable-operation-queue.md
git add marcedit_web tests deploy docker-compose.yml scripts docs/deployment.md
git commit -m "test: verify durable operation queue lifecycle"
```

- [ ] **Step 9: Present the verified commit range before production push**

Run:

```bash
git status --short
git log --oneline --decorate origin/main..HEAD
```

Expected: no TASK-156 tracked changes remain uncommitted; unrelated user files
may still appear and must be named explicitly. Present exact tests, skips,
benchmark results, review outcome, and commits to the user. Push to `origin`
only after the user confirms the production handoff.
