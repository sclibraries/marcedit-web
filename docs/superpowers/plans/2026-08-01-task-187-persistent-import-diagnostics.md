# TASK-187 Persistent Import Diagnostics Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every step is tied to [TASK-187](../../../.tickets/TASK-187-persist-import-diagnostics.md).

**Goal:** Make MarcEdit import outcomes durable, bounded, actionable, and safe across Streamlit reruns, then record evidence strong enough to close TASK-187.

**Architecture:** Keep one session-scoped result object as the only UI source of truth. Normalize and validate that object at the rendering boundary, clear it before every new attempt, and render the result after the importer-triggered rerun. The importer will continue to fail closed and will not add new MarcEdit mappings.

**Tech Stack:** Python 3.9, Streamlit session state, pytest, Docker Compose, existing `marcedit_import`, `task_db`, quota, audit, and Tasks-rendering helpers.

## Global Constraints

- The warning and unresolved source lines remain visible after the import-triggered rerun.
- No rejected conversion may create a task row.
- At most 20 unresolved source lines are retained for display, with an explicit omitted count.
- Result state is session-scoped and never persisted in SQLite or shared across users.
- Unexpected exceptions are logged and shown through a bounded user-facing message.
- Existing MarcEdit conversion compatibility is unchanged; TASK-181, TASK-184, and TASK-185 own new mappings.
- The mounted-source Docker suite must report every skip; no unavailable corpus is treated as a pass.

## Files and Responsibilities

- Modify: `marcedit_web/render/tasks.py` — result normalization, lifecycle, rendering, importer outcome assembly, and dismissal behavior.
- Modify: `tests/test_tasks_workspace_modes.py` — RED/GREEN coverage for the full import-result matrix and lifecycle.
- Modify: `.tickets/TASK-187-persist-import-diagnostics.md` — plan link, implementation evidence, and final status.
- Modify: `docs/superpowers/specs/2026-07-31-task-187-persistent-import-diagnostics-design.md` only if the implementation exposes a necessary contract clarification; otherwise leave the approved design unchanged.

### Task 1: Define the failing result-boundary tests

**Files:**
- Test: `tests/test_tasks_workspace_modes.py`

- [ ] **Step 1: Add malformed-payload tests.** Assert that non-object payloads, non-list `entries`, non-list unresolved lines, and non-numeric omitted counts are discarded without raising.
- [ ] **Step 2: Add the exact unresolved-message test.** Render a rejected result and assert the warning begins with `Not imported: this task contains unresolved external instructions` and includes the structured-controls remediation text.
- [ ] **Step 3: Add dismissal behavior coverage.** Make the fake Streamlit runtime record a rerun and assert Dismiss clears state and requests a rerun.
- [ ] **Step 4: Run the focused tests and verify RED.**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_tasks_workspace_modes.py -k 'import_result or unresolved_text_import or malformed_import'
```

Expected: the new assertions fail against the current implementation because malformed values raise, the required warning copy is absent, and Dismiss does not request a rerun.

### Task 2: Define the importer outcome and lifecycle matrix

**Files:**
- Test: `tests/test_tasks_workspace_modes.py`

- [ ] **Step 1: Add successful text-import coverage.** Assert one saved task, a `success` result, and the imported task name.
- [ ] **Step 2: Add successful archive coverage.** Assert every successful entry is represented and the archive result is durable.
- [ ] **Step 3: Add mixed archive coverage.** Assert imported entries remain saved, unresolved entries remain unsaved, `partial` is reported, and each entry retains its own bounded diagnostics.
- [ ] **Step 4: Add quota and unexpected-exception coverage.** Assert the category and bounded message are preserved without hiding the result behind a transient Streamlit call.
- [ ] **Step 5: Add replacement and lifecycle-reset coverage.** Assert a later attempt replaces the previous object, a new attempt clears before processing, and opening, saving, or cancelling an editor removes unrelated diagnostics.
- [ ] **Step 6: Run the focused tests and verify RED for each missing behavior.**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_tasks_workspace_modes.py -k 'marcedit_import or import_result'
```

Expected: the newly added cases fail only for the unimplemented lifecycle, rendering, or outcome behavior described above.

### Task 3: Implement bounded normalization and lifecycle behavior

**Files:**
- Modify: `marcedit_web/render/tasks.py`

- [ ] **Step 1: Normalize only safe result shapes.** Accept a dictionary with an allowed status and filename, coerce only validated lists of bounded dictionaries, cap displayed unresolved lines at 20, clamp omitted counts to non-negative integers, and discard malformed payloads with a warning log.
- [ ] **Step 2: Clear before processing.** Call `_clear_marcedit_import_result()` before reading or converting a new upload, while retaining the existing result only through ordinary non-import reruns.
- [ ] **Step 3: Preserve the required warning and remediation copy.** Render the exact unresolved warning followed by the bounded source lines and omitted-count caption.
- [ ] **Step 4: Make Dismiss visible immediately.** Clear the session key and call `st.rerun()` after the button click.
- [ ] **Step 5: Keep outcome assembly explicit.** Ensure successful, partial, quota, archive-validation, unresolved, and unexpected outcomes each produce the intended status/category without overwriting a completed result with a later rendering or audit failure.
- [ ] **Step 6: Run the focused tests and verify GREEN.**

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_tasks_workspace_modes.py -k 'marcedit_import or import_result'
```

Expected: all TASK-187 focused tests pass.

### Task 4: Run repository verification and record the disposition

**Files:**
- Modify: `.tickets/TASK-187-persist-import-diagnostics.md`

- [ ] **Step 1: Run the focused Tasks/import suite.**
- [ ] **Step 2: Run the complete mounted-source Docker suite with `-ra`.** Record every skip, including the unavailable institutional corpus and Docker-CLI-dependent Compose checks.
- [ ] **Step 3: Run the native compiler freshness guard and whitespace checks.** Confirm the native manifest is unchanged.
- [ ] **Step 4: Review the final diff for institutional data, vendor records, credentials, and untracked corpus files.**
- [ ] **Step 5: Update the ticket to `Completed` only if all success criteria and the independent review gate are satisfied; otherwise record the exact remaining blocker and leave it `In-Progress`.**

Run:

```bash
docker run --rm --network none \
  -v "$PWD":/workspace:ro -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest -ra
docker compose run --rm marcedit-web pytest -q tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition
git diff --check
```

Expected: no implementation failures, all skips explicitly reported, and no native contract drift.
