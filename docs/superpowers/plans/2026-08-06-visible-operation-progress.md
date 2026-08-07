# Visible Operation Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-197](../../../.tickets/TASK-197-visible-operation-progress.md)

**Goal:** Give catalogers a visible expanded activity panel during long operations and a collapsed completion/error status that survives Quick-path reruns.

**Architecture:** Add `marcedit_web/render/operation_activity.py` as the single presentation helper. It owns `st.status`, optional `st.progress`, throttled progress messages, and a bounded serializable session completion record. Existing Quick and saved-task engines keep their request construction, sandbox calls, persistence, and error paths; `render/tasks.py` only supplies phase labels and callbacks.

**Tech Stack:** Python 3.9, Streamlit 1.50, pytest, existing Quick progress callbacks, Docker Compose.

## Global Constraints

- TASK-197 remains `In-Progress` until the authenticated Docker browser scenarios and the final code review pass.
- No worker, queue, database, file, sandbox, cancellation, timeout, or MARC-semantic changes.
- Live Streamlit status objects never enter session state; only the bounded completion summary does.
- Completion summaries contain only operation identity, phase/state, bounded label, and bounded message; no record content, request values, or tracebacks.
- Reuse `_quick_batch_progress`'s 250-record cadence; do not create a second throttle.
- Totals of zero or unknown must show an explicit progress-unavailable message, never a silent zero bar.
- Quick operation changes clear stale completion summaries along with existing preview/export artifacts.

---

### Task 1: Build and test the shared activity helper

**Files:**
- Create: `marcedit_web/render/operation_activity.py`
- Create: `tests/test_operation_activity.py`

**Interfaces:**
- Produces `operation_activity.open_activity(operation_id, label, *, phase, total=None)`, yielding an `ActivityHandle`.
- `ActivityHandle.phase(label, message)`, `.progress_callback(processed, total)`, `.complete(label, message)`, and `.fail(label, message)` update the current panel.
- Produces `operation_activity.render_completion(operation_id) -> bool` and `operation_activity.clear_completion(operation_id: str | None = None) -> None`.

- [ ] **Step 1: Write failing helper tests**

In `tests/test_operation_activity.py`, define the test doubles before the tests:
`FakeStatusFactory` is callable, records `(label, expanded)` in `created`, and
returns a `FakeStatus` whose `update()` keyword dictionaries are recorded in
`updates`; `FakeProgressFactory` is callable, records each numeric value passed
to its returned object's `.progress()`, and exposes those values as `values`;
`FakePlaceholder` records each string passed to `.write()` or `.markdown()`;
and `FakeStreamlit` exposes `session_state` (a dict), `status` (the callable
status factory), `progress` (the callable progress factory), `.empty()`, and
`.write()`. This keeps the tests independent of Streamlit while making every
asserted interaction explicit.

Use that fake Streamlit status/progress/empty implementation and assert
behavior rather than implementation details:

```python
def test_activity_starts_expanded_and_finishes_collapsed(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)

    with operation_activity.open_activity(
        "quick-field-change-preview",
        "Quick field change",
        phase="Preparing",
        total=1000,
    ) as activity:
        activity.phase("Previewing", "Running in the sandbox")
        activity.complete("Preview ready", "Review the changes below.")

    assert fake.status.created == [("Quick field change", True)]
    assert fake.messages[0] == "Preparing…"
    assert fake.status.updates[-1] == {
        "label": "Preview ready",
        "state": "complete",
        "expanded": False,
    }
    assert fake.session_state[operation_activity.COMPLETION_KEY] == {
        "operation_id": "quick-field-change-preview",
        "state": "complete",
        "label": "Preview ready",
        "message": "Review the changes below.",
    }


def test_progress_uses_existing_first_boundary_and_throttle(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)
    with operation_activity.open_activity(
        "quick-batch-preview", "Quick batch", phase="Previewing", total=1000
    ) as activity:
        for value in (1, 2, 250, 251, 500, 1000):
            activity.progress_callback(value, 1000)

    assert fake.progress.values == [0.0, 0.001, 0.25, 0.5, 1.0]
    assert fake.messages == [
        "Previewing record 1 of 1,000…",
        "Previewing record 250 of 1,000…",
        "Previewing record 500 of 1,000…",
        "Previewing record 1,000 of 1,000…",
    ]


def test_zero_total_reports_progress_unavailable(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)
    with operation_activity.open_activity(
        "find-preview", "Find and replace", phase="Preparing", total=0
    ) as activity:
        activity.progress_callback(0, 0)

    assert any("Progress unavailable" in message for message in fake.messages)
    assert fake.progress.created == []


def test_unknown_total_reports_progress_unavailable(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)
    with operation_activity.open_activity(
        "find-preview", "Find and replace", phase="Preparing", total=None
    ) as activity:
        activity.progress_callback(1, 0)

    assert any("Progress unavailable" in message for message in fake.messages)
    assert fake.progress.created == []


def test_render_completion_and_clear_are_operation_scoped(monkeypatch):
    fake = FakeStreamlit(
        session_state={
            operation_activity.COMPLETION_KEY: {
                "operation_id": "quick-batch-preview",
                "state": "complete",
                "label": "Preview ready",
                "message": "Review below.",
            }
        }
    )
    monkeypatch.setattr(operation_activity, "st", fake)

    assert operation_activity.render_completion("quick-batch-preview")
    assert not operation_activity.render_completion("quick-field-change-preview")
    operation_activity.clear_completion("quick-batch-preview")
    assert operation_activity.COMPLETION_KEY not in fake.session_state
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_operation_activity.py
```

Expected: FAIL because the helper module and interfaces do not exist.

- [ ] **Step 3: Implement the helper**

Use one bounded session key, `operation_activity_completion`. `open_activity`
must create `st.status(label, expanded=True)`, write the initial phase as
`"{phase}…"`, create a progress bar only for a positive total, and an
`st.empty()` message placeholder. `ActivityHandle` must
reuse the existing cadence: render record 1, every 250 records, and the final
record; ignore intermediate values. For `total <= 0`, write exactly
`Progress unavailable — processing records…` to the message placeholder and do
not create a progress bar. `complete` and `fail` update the current status and
write the serializable summary; `render_completion` replays that summary in a
collapsed `st.status` and returns whether it matched the requested operation.

- [ ] **Step 4: Run helper tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_operation_activity.py
```

Expected: all helper tests pass with zero skips.

- [ ] **Step 5: Commit**

```bash
git add marcedit_web/render/operation_activity.py tests/test_operation_activity.py
git commit -m "feat: add shared operation activity helper"
```

---

### Task 2: Integrate focused Quick field changes and Quick rerun summaries

**Files:**
- Modify: `marcedit_web/render/tasks.py` in `_render_quick_ops_mode`, `_build_quick_field_change_preview`, and `_apply_quick_field_change_preview`
- Modify: `marcedit_web/render/tasks.py` in `_clear_quick_operation_state`
- Modify: `tests/test_task_quick_field_changes.py`
- Modify: `tests/test_quick_field_changes_render.py`

**Interfaces:**
- Consumes `operation_activity.open_activity`, `render_completion`, and `clear_completion`.
- Passes `ActivityHandle.progress_callback` to `quick_field_change_runner.build_preview` and `build_apply_candidate`.
- Uses operation IDs `quick-field-change-preview` and `quick-field-change-apply`.

- [ ] **Step 1: Add failing focused integration tests**

Patch the existing runner fakes to record the `progress` keyword. Define a
local `RecordingActivity` context manager with `phase_calls`,
`progress_calls`, `completed`, and `failed` lists; its methods append their
arguments and its `progress_callback` is callable. Monkeypatch
`operation_activity.open_activity` to return that context manager. Invoke the
existing focused-preview fixture with a deterministic request and assert that
the runner received a callable `progress`, that the activity received the
runner's progress callback, and that completion wrote the expected label and
message. Use the existing `_store(tmp_path)`, `_preview(store)`,
`_candidate(tmp_path)`, and `QuickFieldChangeRequest` factories in
`tests/test_task_quick_field_changes.py`; do not invent a second request or
preview representation. Repeat the same setup for apply, including the
existing rerun path, and assert `complete()` occurs before the rerun is
requested.

Add a rerun-focused test using the module's existing Streamlit fake. Seed
`session_state[operation_activity.COMPLETION_KEY]` with the
`quick-field-change-apply` summary, render that same focused operation, and
assert the final status is collapsed. Change the selected operation to the
existing `batch:035-oclc` value, render again, and assert the completion key and
the focused preview artifact are both cleared. Load the renderer through the
existing `_tasks_render(monkeypatch, fake_st)` helper and exercise its current
`_render_quick_ops_mode` entry point.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
PYTHONPATH=. pytest -q tests/test_task_quick_field_changes.py tests/test_quick_field_changes_render.py
```

Expected: the new callback and rerun-summary assertions fail while existing
Quick behavior remains green.

- [ ] **Step 3: Integrate the helper**

Wrap focused preview/apply work in `open_activity` with explicit phases and
pass `progress=activity.progress_callback`. Call `complete` before the apply
path's existing `st.rerun()` and call `fail` on existing bounded exception and
result-error paths. Render the matching completion summary in the selected
Quick operation and clear all activity summaries from
`_clear_quick_operation_state`.

- [ ] **Step 4: Run focused tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_task_quick_field_changes.py tests/test_quick_field_changes_render.py tests/test_quick_field_change_runner.py tests/test_quick_field_changes.py
```

- [ ] **Step 5: Commit**

```bash
git add marcedit_web/render/tasks.py tests/test_task_quick_field_changes.py tests/test_quick_field_changes_render.py
git commit -m "feat: show focused quick operation activity"
```

---

### Task 3: Integrate Quick batch and Find and replace

**Files:**
- Modify: `marcedit_web/render/tasks.py` in `_build_and_store_quick_batch_preview`, `_apply_quick_batch_preview`, `_build_and_store_preview`, and `_apply_quick_preview`
- Modify: `marcedit_web/render/tasks.py` to remove the duplicate `_quick_batch_progress` renderer after its behavior is covered by the helper
- Modify: `tests/test_quick_batch_render.py`
- Modify: `tests/test_quick_batch.py`
- Modify: `tests/test_batch_replace.py`

**Interfaces:**
- Uses operation IDs `quick-batch-preview`, `quick-batch-apply`, `quick-find-replace-preview`, and `quick-find-replace-apply`.
- Keeps `quick_batch.build_preview(..., progress=...)` and `quick_batch.apply_preview(..., progress=...)` request/result behavior unchanged.
- Uses phase-only activity updates for `batch_replace`, which has no progress parameter.

- [ ] **Step 1: Add failing tests**

In `tests/test_quick_batch_render.py`, use its existing `_FakeStreamlit` and
`_tasks_render` helpers. Add the same local `RecordingActivity` protocol used
by Task 2, with `phase_calls`, `progress_calls`, `completed`, and `failed`
lists, and monkeypatch `open_activity` to return it. Use the existing Quick
batch fixture for a `QuickBatchRequest(kind="leader", position="05",
value="c")`; do not create a second store or request factory. Assert that the
runner receives `progress=activity.progress_callback`, that callbacks at
records 1, 250, and 1,000 are forwarded exactly once, and that completion is
recorded before the existing rerun. Add Find and replace tests using the
module's existing `BatchReplaceRequest` fixture, asserting the phase labels
`Preparing`, `Previewing`, and `Finalizing` while the request and returned
preview remain unchanged.

- [ ] **Step 2: Run tests and confirm RED**

```bash
PYTHONPATH=. pytest -q tests/test_quick_batch_render.py tests/test_quick_batch.py tests/test_batch_replace.py
```

Expected: new shared-helper lifecycle assertions fail; existing operation
assertions identify any accidental request/result changes.

- [ ] **Step 3: Integrate without changing engines**

Replace `_quick_batch_progress` construction with the helper's callback, using
the helper's existing first/250/last cadence. Wrap Find and replace in the
phase-only helper. Complete or fail each activity before any existing rerun;
write the session completion summary so the next Quick render shows it beside
preview/export evidence.

- [ ] **Step 4: Run Quick tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_quick_batch_render.py tests/test_quick_batch.py tests/test_batch_replace.py tests/test_task_quick_field_changes.py tests/test_quick_field_changes_render.py
```

- [ ] **Step 5: Commit**

```bash
git add marcedit_web/render/tasks.py tests/test_quick_batch_render.py tests/test_quick_batch.py tests/test_batch_replace.py
git commit -m "feat: show quick batch activity progress"
```

---

### Task 4: Consolidate saved-task run status

**Files:**
- Modify: `marcedit_web/render/tasks.py` around `_execute_synchronous_run`
- Modify: `tests/test_tasks_export.py`
- Modify: `tests/test_synchronous_task_runner.py` for the saved-task renderer status fake

**Interfaces:**
- Replaces the local `st.status("Running tasks…")` lifecycle in
  `_execute_synchronous_run` with
  `operation_activity.open_activity("saved-task-run", "Running tasks…", phase="Preparing", total=None)`;
  saved-task runs have no progress callback, so the panel explicitly reports
  that progress is unavailable instead of showing a misleading zero bar.
- Keeps the existing `synchronous_task_runner.run_tasks` call, timeout/error labels, output parsing, and result evidence unchanged.

- [ ] **Step 1: Add a status-helper integration assertion**

Patch the existing saved-task fake in `tests/test_tasks_export.py` so it records
helper calls. Use the existing `TaskSpec` and sandbox-result fixtures rather
than constructing a new runner; assert the run reports preparation, sandbox
execution, and collapsed completion/error states without changing the returned
sandbox result. Use `tests/test_synchronous_task_runner.py` only for the
unchanged engine-level timeout/error assertions.

- [ ] **Step 2: Run the test and confirm RED**

```bash
PYTHONPATH=. pytest -q tests/test_tasks_export.py -k "status or run"
```

Expected: the helper invocation assertion fails while existing run behavior
remains unchanged.

- [ ] **Step 3: Replace only the presentation wrapper**

Use the helper around the current saved-task body. Map timeout and nonzero exit
to `.fail(...)`; map successful output to `.complete("Done — review the result below", ...)`.
Do not alter task specs, sandbox inputs, or output parsing.

- [ ] **Step 4: Run saved-task tests GREEN**

```bash
PYTHONPATH=. pytest -q tests/test_tasks_export.py tests/test_synchronous_task_runner.py
```

- [ ] **Step 5: Commit**

```bash
git add marcedit_web/render/tasks.py tests/test_tasks_export.py
git commit -m "refactor: share saved-task activity status"
```

---

### Task 5: Full verification, browser acceptance, and ticket closure

**Files:**
- Modify: `.tickets/TASK-197-visible-operation-progress.md`

- [ ] **Step 1: Run the focused suite**

```bash
PYTHONPATH=. pytest -q tests/test_operation_activity.py tests/test_task_quick_field_changes.py tests/test_quick_field_changes_render.py tests/test_quick_batch_render.py tests/test_quick_batch.py tests/test_batch_replace.py tests/test_tasks_export.py tests/test_synchronous_task_runner.py
```

Record exact pass/fail/skip counts.

- [ ] **Step 2: Run the authoritative Docker suite**

```bash
docker compose -p task197-verify -f docker-compose.yml run --rm --no-deps \
  -v "$PWD:/app:ro" \
  -v "$PWD/data:/app/data:rw" \
  marcedit-web python -m pytest -q
```

Do not describe skips as passes; record every skip reason.

- [ ] **Step 3: Run authenticated browser acceptance on `localhost:8501`**

As `roconnell@smith.edu`, open Tasks → Quick changes with a loaded MARC file
and verify:

1. A long focused Quick preview shows an expanded in-page activity panel with
   a phase and record progress while the sandbox runs.
2. Completion rerenders as a collapsed status beside preview evidence after
   the Quick-path rerun.
3. Quick batch preview uses the same panel and preserves its existing progress
   cadence.
4. Find and replace shows phase-only activity and preserves its preview.
5. A timeout or validation failure leaves a readable collapsed error and the
   existing bounded error message.
6. Changing the Quick operation clears the old completion summary and preview
   evidence.

- [ ] **Step 4: Request code review**

Review the implementation range for session-summary bounds, operation scoping,
status cleanup, progress cadence, rerun ordering, and unchanged engine calls.
Resolve all Critical and Important findings, then rerun Steps 1–3.

- [ ] **Step 5: Complete the ticket**

Append exact test counts, browser evidence, review outcome, and final commits
to TASK-197. Change `Status: In-Progress` to `Status: Completed` only after
the full verification and review pass.

- [ ] **Step 6: Commit ticket evidence**

```bash
git add .tickets/TASK-197-visible-operation-progress.md
git commit -m "docs: record TASK-197 completion evidence"
```

Do not push or merge as part of this plan.
