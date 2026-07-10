# Large-Batch Memory and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-147](../../../.tickets/TASK-147-large-batch-memory-performance.md)

**Goal:** Bound memory and make View/Edit and synchronous batch workflows responsive at 50K-100K records under a 2 GB Red Hat service limit.

**Architecture:** Retain `RecordStore` and MRC files, but make random access truly indexed. Replace whole-batch Python values at batch boundaries with paths, compact revision-bound summaries, and streamed disk-to-disk operations.

**Tech Stack:** Python 3.11, Streamlit, pymarc, pytest, systemd/cgroup v2.

## Global Constraints

- Follow TDD: every production behavior starts with a failing intent-focused test.
- Preserve synchronous workflows, MARC order, rollback snapshots, and sandbox limits.
- Do not retain full MRC bytes or all parsed records in Streamlit session state.
- Keep the private service at `MemoryMax=2G`; heavy-operation concurrency defaults to two.
- Touch only TASK-147 behavior and leave unrelated worktree changes untouched.

---

### Task 1: Indexed RecordStore Access

**Files:**
- Modify: `marcedit_web/lib/record_store.py`
- Test: `tests/test_record_store.py`

**Interfaces:**
- Produces: `RecordStore.revision: int`
- Produces: `RecordStore.replace_from_path(source_path: Path) -> int`
- Preserves: `get`, `iter_records`, `replace`, `delete`, `append`, `persist_to_disk`

- [x] Add failing tests proving last-position `get` parses one record, mutations preserve live order, revision changes on content mutation, reindex avoids `Path.read_bytes`, and path replacement is atomic.
- [x] Run the focused tests and confirm each fails for the intended missing behavior.
- [x] Implement the compact live-index mapping, direct reads, revision, mmap reindex helper, and path-backed replacement.
- [x] Run all RecordStore tests and commit the independently usable storage change.

### Task 2: O(1) View Navigation And Revision-Bound Search

**Files:**
- Modify: `marcedit_web/render/view.py`
- Test: `tests/test_viewer.py`
- Test: `tests/test_app_pages.py`

**Interfaces:**
- Consumes: `RecordStore.revision`
- Produces: compact search state keyed by `(query text, store revision)`

- [x] Add failing render/helper tests proving unfiltered navigation does not construct all record numbers and unchanged search navigation does not rescan the store.
- [x] Run the focused tests and verify the expected failure.
- [x] Extract minimal navigation/search helpers and update the renderer to use arithmetic or cached match positions.
- [x] Run View tests and commit the interactive performance change.

### Task 3: Path-Backed Sandbox And Diff Contracts

**Files:**
- Modify: `marcedit_web/lib/sandbox.py`
- Modify: `marcedit_web/lib/task_diff.py`
- Modify: `marcedit_web/render/tasks.py`
- Test: `tests/test_sandbox.py`
- Test: `tests/test_task_diff.py`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Produces: `SandboxResult.output_path: Path`
- Produces: `compute_task_diff(input_path: Path, output_path: Path, ...)`

- [x] Add failing tests that forbid reading sandbox output/input into whole-file bytes and exercise path-to-path diffing.
- [x] Run the tests and confirm failures identify the bytes contracts.
- [x] Return sandbox output paths, stream both diff inputs, and migrate task-run callers/session results to paths and counts.
- [x] Run sandbox/task/diff tests and commit the path-backed execution boundary.

### Task 4: Streamed Previews, Applies, And Snapshots

**Files:**
- Modify: `marcedit_web/lib/quick_batch.py`
- Modify: `marcedit_web/lib/batch_replace.py`
- Modify: `marcedit_web/lib/provenance.py`
- Modify: `marcedit_web/lib/snapshot_actions.py`
- Modify: affected render flows in `marcedit_web/render/`
- Test: corresponding quick-batch, replace, snapshot, editor, and history tests

**Interfaces:**
- Preview values carry `store_revision`, counts, capped summaries, and paths only.
- Snapshot creation consumes `before_path: Path` and `after_path: Path`.

- [ ] Add failing tests that reject full record lists/bytes, prove revision-based stale detection, preserve rollback files, and clean failed/superseded artifacts.
- [ ] Verify the failures before production edits.
- [ ] Stream preview/apply output, atomically call `replace_from_path`, and migrate every whole-batch snapshot caller to disk-to-disk copies.
- [ ] Run all affected flow tests and commit the bounded-memory mutation pipeline.

### Task 5: Admission Control And Performance Telemetry

**Files:**
- Create: `marcedit_web/lib/batch_runtime.py`
- Modify: heavy operation render entry points
- Test: `tests/test_batch_runtime.py`

**Interfaces:**
- Produces: `batch_slot(operation: str)` context manager
- Produces: `measure_operation(operation: str, **dimensions)` context manager

- [ ] Add failing tests for the default two-slot gate, env override, waiting/release behavior, exception release, and normalized RSS logging.
- [ ] Run the tests and confirm the missing module/behavior failures.
- [ ] Implement the process-wide semaphore and structured timer, then wrap saved-task and quick-operation execution.
- [ ] Run focused and concurrency tests and commit the runtime guardrail.

### Task 6: Red Hat Configuration, Benchmarks, And Completion

**Files:**
- Modify: `deploy/marcedit-web-private.service`
- Modify: `docs/deployment.md`
- Create: `scripts/benchmark-large-batch.py`
- Test: `tests/test_deploy_units.py`
- Test: `tests/test_large_batch_benchmark.py`

- [ ] Add failing configuration tests for `MemoryHigh=1536M` and the documented cgroup-v2 condition for `MemorySwapMax=0`.
- [ ] Add an opt-in synthetic 100K benchmark covering last-record lookup, standard quick operation, counts, duration, and RSS.
- [ ] Implement unit/docs/benchmark changes and run focused verification.
- [ ] Run the complete suite, the benchmark at practical local scale, and static checks; record exact evidence in TASK-147.
- [ ] Perform code review, resolve all Critical/Important findings, mark TASK-147 Completed, and commit the completion evidence.
