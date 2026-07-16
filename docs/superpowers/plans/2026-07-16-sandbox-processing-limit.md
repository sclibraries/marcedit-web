# TASK-155 Sandbox Processing Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise saved-task sandbox CPU and elapsed-processing limits from 30 seconds to a shared 300-second default, use plain-language timeout copy, and prevent timed-out partial output from being downloaded or applied.

**Architecture:** Keep the synchronous saved-task flow intact for this temporary production-testing bridge. `marcedit_web.lib.sandbox` owns one default processing-limit constant and passes each invocation's effective limit to the parent elapsed timeout, the pre-exec CPU limit, and the inlined child driver's defensive CPU limit. `marcedit_web.render.tasks` uses that shared value in help copy and treats timed-out output as diagnostic-only, returning before all publish actions.

**Tech Stack:** Python 3.9, Streamlit, POSIX `resource.setrlimit`, `subprocess`, pytest, pymarc

**Ticket:** [TASK-155](../../../.tickets/TASK-155-sandbox-processing-limit.md)

**Design:** [Approved design](../specs/2026-07-16-sandbox-processing-limit-design.md)

## Global Constraints

- Python remains `>=3.9,<3.10`; do not use syntax introduced after Python 3.9.
- Default processing limit is exactly 300 seconds.
- Parent elapsed timeout, pre-exec CPU limit, and in-child CPU limit derive from the same invocation value.
- An injected fractional elapsed timeout rounds up to at least one CPU second.
- Stable low-level `sandbox-timeout` codes and audit event names do not change.
- Timed-out output may remain on disk for diagnostics but is neither downloadable nor adoptable.
- No queue, worker, chunking, resumability, merge, split, new dependency, or deployment setting belongs in TASK-155.
- Preserve unrelated workspace changes and untracked runtime data.
- Follow strict red-green-refactor: no production edit before its failing test is observed.
- Mark the ticket `In-Progress` when the implementation worktree is created; mark it `Completed` only after all tests and code review pass.

## File Structure

- Modify `.tickets/TASK-155-sandbox-processing-limit.md`: lifecycle status and final verification evidence.
- Modify `marcedit_web/lib/sandbox.py`: shared processing-limit ownership and aligned parent/child enforcement.
- Modify `tests/test_sandbox.py`: intent-focused default-limit, injected-limit, and runaway-code coverage.
- Modify `marcedit_web/render/tasks.py`: five-minute help, plain-language timeout copy, and timeout publish gate.
- Modify `tests/test_tasks_export.py`: timeout copy, run-panel help, and partial-output action coverage.

No other file is required. In particular, do not modify the queue or merge/split tickets during TASK-155 implementation.

---

### Task 1: Align sandbox processing limits

**Files:**
- Modify: `.tickets/TASK-155-sandbox-processing-limit.md`
- Modify: `tests/test_sandbox.py`
- Modify: `marcedit_web/lib/sandbox.py`

**Interfaces:**
- Consumes: `run_tasks_subprocess(tasks, record_bytes=None, *, input_path=None, timeout=..., tmp_dir=None) -> SandboxResult`
- Produces: `sandbox.DEFAULT_PROCESSING_LIMIT_SECONDS: int` with value `300`
- Produces: `_cpu_limit_seconds(timeout: float) -> int`
- Preserves: `run_tasks_subprocess` keyword compatibility for callers that inject `timeout`

- [ ] **Step 1: Create the isolated worktree and mark TASK-155 In-Progress**

Use `superpowers:using-git-worktrees` before editing. In that worktree, change only the ticket status line:

```markdown
Status: In-Progress
```

Confirm the worktree starts from commit `a873752` or a descendant containing the approved design and all three ticket files.

- [ ] **Step 2: Write failing tests for shared default and injected CPU enforcement**

Add `SimpleNamespace` and the following tests to `tests/test_sandbox.py`. Keep the existing POSIX skip marker.

```python
from types import SimpleNamespace


def test_default_processing_limit_reaches_parent_and_child(
    one_record_bytes, monkeypatch,
):
    """Large legitimate runs get one shared five-minute safety budget."""
    captured = {}
    resource_limits = []

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs["timeout"]
        captured["preexec_fn"] = kwargs["preexec_fn"]
        return SimpleNamespace(stderr="", returncode=0)

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sandbox.resource,
        "setrlimit",
        lambda resource_id, value: resource_limits.append(
            (resource_id, value)
        ),
    )

    run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        one_record_bytes,
    )
    captured["preexec_fn"]()

    assert sandbox.DEFAULT_PROCESSING_LIMIT_SECONDS == 300
    assert captured["timeout"] == 300
    cpu_arg = captured["cmd"].index("--cpu-seconds")
    assert captured["cmd"][cpu_arg + 1] == "300"
    assert (
        sandbox.resource.RLIMIT_CPU,
        (300, 300),
    ) in resource_limits


def test_fractional_timeout_uses_one_cpu_second(
    one_record_bytes, monkeypatch,
):
    """Fast tests never turn a fractional timeout into a zero CPU limit."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(stderr="", returncode=0)

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)

    run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        one_record_bytes,
        timeout=0.1,
    )

    cpu_arg = captured["cmd"].index("--cpu-seconds")
    assert captured["timeout"] == 0.1
    assert captured["cmd"][cpu_arg + 1] == "1"


def test_injected_timeout_reaches_child_cpu_limit(one_record_bytes):
    """The defensive in-child CPU limit matches the invocation budget."""
    result = run_tasks_subprocess(
        [TaskSpec(
            name="inspect-limit",
            body=(
                "import resource\n"
                "cpu_limit = resource.getrlimit(resource.RLIMIT_CPU)[0]\n"
                "assert cpu_limit == 2, cpu_limit\n"
            ),
        )],
        one_record_bytes,
        timeout=2.0,
    )

    assert result.returncode == 0
    assert result.errors == []
```

Extend the existing runaway test so the structured diagnostic shown in the UI
also uses plain language:

```python
def test_long_running_task_times_out(one_record_bytes):
    """Runaway task code is stopped with a user-readable diagnostic."""
    result = run_tasks_subprocess(
        [TaskSpec(name="busy", body="while True:\n    pass\n")],
        one_record_bytes,
        timeout=2.0,
    )

    assert result.timed_out is True
    timeout_error = next(
        error for error in result.errors
        if error["code"] == "sandbox-timeout"
    )
    assert "maximum processing time" in timeout_error["message"]
    assert "wall clock" not in timeout_error["message"]
```

- [ ] **Step 3: Run the new sandbox tests and verify RED**

Run:

```bash
pytest tests/test_sandbox.py::test_default_processing_limit_reaches_parent_and_child tests/test_sandbox.py::test_fractional_timeout_uses_one_cpu_second tests/test_sandbox.py::test_injected_timeout_reaches_child_cpu_limit tests/test_sandbox.py::test_long_running_task_times_out -q
```

Expected: all four tests fail: the three new tests fail because `DEFAULT_PROCESSING_LIMIT_SECONDS` and the `--cpu-seconds` driver argument do not exist and the current in-child CPU limit remains 30 seconds when the caller injects two seconds; the updated runaway test fails because its terminal diagnostic still says `wall clock`.

- [ ] **Step 4: Implement the shared effective processing limit**

In `marcedit_web/lib/sandbox.py`:

1. Import `math` and `partial`.
2. Replace `_CPU_SECONDS = 30` with the public default.
3. Make the driver parse `--cpu-seconds` before importing pymarc or project transforms.
4. Set the defensive child CPU limit from that parsed value.
5. Convert each invocation's elapsed timeout into a positive whole CPU-second value.
6. Pass that same value to the child command and pre-exec callback.

Use these definitions and call shapes:

```python
import math
from functools import partial


DEFAULT_PROCESSING_LIMIT_SECONDS = 300


def _cpu_limit_seconds(timeout: float) -> int:
    """Return a positive whole-second CPU budget for an elapsed timeout."""
    return max(1, math.ceil(timeout))


def _preexec_set_limits(cpu_seconds: int) -> None:
    """Apply resource limits in the child between fork and exec."""
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (cpu_seconds, cpu_seconds),
    )
    resource.setrlimit(resource.RLIMIT_AS, (_AS_BYTES, _AS_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (_NPROC, _NPROC))
```

Update the public function default and derive the effective CPU seconds once:

```python
def run_tasks_subprocess(
    tasks: Iterable[TaskSpec],
    record_bytes: Optional[bytes] = None,
    *,
    input_path: Optional[Path] = None,
    timeout: float = DEFAULT_PROCESSING_LIMIT_SECONDS,
    tmp_dir: Optional[Path] = None,
) -> SandboxResult:
    cpu_seconds = _cpu_limit_seconds(timeout)
```

Add the child argument to `cmd`:

```python
        "--max-errors", str(MAX_RETAINED_ERRORS),
        "--cpu-seconds", str(cpu_seconds),
```

Use the invocation-specific pre-exec callback:

```python
            preexec_fn=partial(_preexec_set_limits, cpu_seconds),
```

Within `_DRIVER_SCRIPT`, replace the hard-coded early `_set_limits()` call and later argument parsing with one early parse. The complete ordering must be:

```python
def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--max-errors", required=True, type=int)
    ap.add_argument("--cpu-seconds", required=True, type=int)
    return ap.parse_args()


def _set_limits(cpu_seconds):
    try:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (cpu_seconds, cpu_seconds),
        )
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,
                                                 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024 * 1024,
                                                    1024 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except (ValueError, resource.error):
        pass


args = _parse_args()
_set_limits(args.cpu_seconds)

import pymarc
from marcedit_web.lib import transforms


def main():
    with open(args.tasks) as f:
        tasks = json.load(f)
```

Keep the remainder of `main()` unchanged, using the module-level parsed `args`, and keep `main()` under the existing `if __name__ == "__main__"` guard. Do not add configuration or workload scaling.

Keep the stable `sandbox-timeout` code but replace its user-visible diagnostic:

```python
            "message": (
                f"sandbox exceeded {timeout:.0f}s maximum processing time"
            ),
```

- [ ] **Step 5: Run the sandbox tests and verify GREEN**

Run:

```bash
pytest tests/test_sandbox.py::test_default_processing_limit_reaches_parent_and_child tests/test_sandbox.py::test_fractional_timeout_uses_one_cpu_second tests/test_sandbox.py::test_injected_timeout_reaches_child_cpu_limit tests/test_sandbox.py::test_long_running_task_times_out tests/test_sandbox.py::test_noop_task_round_trips -q
```

Expected: `5 passed` and no skips, warnings, or leaked child processes.

- [ ] **Step 6: Run the complete sandbox suite**

Run:

```bash
pytest tests/test_sandbox.py -q
```

Expected on POSIX: all sandbox tests pass with no skips. On a non-POSIX host, stop and report the module-level skip instead of claiming sandbox verification.

- [ ] **Step 7: Commit Task 1**

```bash
git add .tickets/TASK-155-sandbox-processing-limit.md tests/test_sandbox.py marcedit_web/lib/sandbox.py
git commit -m "fix: align sandbox processing limit at five minutes"
```

---

### Task 2: Make timeout results clear and non-publishable

**Files:**
- Modify: `tests/test_tasks_export.py`
- Modify: `marcedit_web/render/tasks.py`

**Interfaces:**
- Consumes: `sandbox.DEFAULT_PROCESSING_LIMIT_SECONDS`
- Produces: `TASK_TIMEOUT_STATUS: str`
- Produces: `TASK_TIMEOUT_MESSAGE: str`
- Preserves: successful saved-task download and job-file adoption behavior

- [ ] **Step 1: Write failing tests for user copy and timeout action gates**

Add `multiselect` to `_FakeStreamlit` in `tests/test_tasks_export.py`:

```python
    def multiselect(self, _label, *, options, default, **_kwargs):
        return list(default)
```

Add the run-panel test:

```python
def test_run_panel_explains_the_five_minute_processing_limit(monkeypatch):
    """Catalogers see the real temporary budget before starting work."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)

    tasks_render._render_run_panel([], Path("/unused"))

    rendered = " ".join(fake_st.captions)
    assert "5 minutes" in rendered
    assert "wall-clock" not in rendered
```

Replace `test_render_run_results_does_not_read_output_when_diff_summary_missing` with this intent-focused timeout test:

```python
def test_timed_out_task_output_is_not_publishable(monkeypatch, tmp_path):
    """An incomplete MARC prefix is diagnostic evidence, not an export."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    input_path = tmp_path / "input.mrc"
    output_path = tmp_path / "partial-output.mrc"
    input_path.write_bytes(b"input")
    output_path.write_bytes(b"partial")
    fake_st.session_state[tasks_render.K_RUN_RESULTS] = {
        "issues": [],
        "out_filename": "source_tasks_20260709_190000.mrc",
        "out_path": str(output_path),
        "input_count": 60_498,
        "output_count": 43_762,
        "ran_tasks": ["Leader cleanup"],
        "timed_out": True,
        "sandbox_returncode": 124,
        "sandbox_input_path": str(input_path),
        "_diff_summary": None,
        "snapshot_id": None,
    }

    tasks_render._render_run_results()

    assert tasks_render.TASK_TIMEOUT_STATUS == (
        "⚠️ Run reached the maximum processing time"
    )
    assert fake_st.errors == [tasks_render.TASK_TIMEOUT_MESSAGE]
    assert "maximum processing time" in fake_st.errors[0]
    assert "wall-clock" not in fake_st.errors[0]
    assert fake_st.buttons == []
    assert fake_st.download_buttons == []
    assert not any(
        "output is ready" in message.lower()
        for message in fake_st.markdowns
    )
```

- [ ] **Step 2: Run the new render tests and verify RED**

Run:

```bash
pytest tests/test_tasks_export.py::test_run_panel_explains_the_five_minute_processing_limit tests/test_tasks_export.py::test_timed_out_task_output_is_not_publishable -q
```

Expected: the first test fails because the panel still says 30 seconds and `wall-clock`; the second fails because `TASK_TIMEOUT_MESSAGE` does not exist and the partial output still gets a Prepare Download action.

- [ ] **Step 3: Implement plain-language copy and the timeout publish gate**

Near the Tasks render module's other constants, add:

```python
TASK_TIMEOUT_STATUS = "⚠️ Run reached the maximum processing time"
TASK_TIMEOUT_MESSAGE = (
    "This run exceeded the 5-minute processing limit and stopped before "
    "all records were completed. No partial output was applied or made "
    "available for download."
)
```

In `_render_run_panel`, derive the duration from the sandbox constant and replace the current 30-second/wall-clock caption:

```python
    processing_minutes = sandbox.DEFAULT_PROCESSING_LIMIT_SECONDS // 60
    st.caption(
        "ℹ️ Runs apply in the sandbox, which has CPU, memory, and maximum "
        f"processing-time limits. Large batches may take up to "
        f"{processing_minutes} minutes — **leave this tab open until the "
        "status below reports Done**."
    )
```

In `_execute_sandboxed_run`, replace only the timeout status label:

```python
            status.update(
                label=TASK_TIMEOUT_STATUS,
                state="error",
                expanded=False,
            )
```

In `_render_run_results`, use the plain-language message:

```python
    if results.get("timed_out"):
        st.error(TASK_TIMEOUT_MESSAGE)
```

After issues and `_render_diff_review(results)` have rendered, return before all publish actions when the run timed out:

```python
    _render_diff_review(results)

    if results.get("timed_out"):
        return
```

Do not delete the partial file here; run history may retain its path and record count for diagnostics. Do not broaden this gate to non-timeout sandbox exits in TASK-155.

- [ ] **Step 4: Run the render tests and verify GREEN**

Run:

```bash
pytest tests/test_tasks_export.py::test_run_panel_explains_the_five_minute_processing_limit tests/test_tasks_export.py::test_timed_out_task_output_is_not_publishable tests/test_tasks_export.py::test_render_run_results_uses_output_path_without_session_bytes tests/test_tasks_export.py::test_saved_task_output_requires_explicit_version_adoption -q
```

Expected: `4 passed`. The two successful-run tests prove the timeout gate did not remove normal download or version adoption.

- [ ] **Step 5: Run all Tasks export tests**

Run:

```bash
pytest tests/test_tasks_export.py -q
```

Expected: all tests pass with no skips.

- [ ] **Step 6: Commit Task 2**

```bash
git add tests/test_tasks_export.py marcedit_web/render/tasks.py
git commit -m "fix: make timed-out task output non-publishable"
```

---

### Task 3: Verify, review, and complete TASK-155

**Files:**
- Modify: `.tickets/TASK-155-sandbox-processing-limit.md`

**Interfaces:**
- Consumes: completed Task 1 and Task 2 commits
- Produces: a reviewed, fully verified TASK-155 branch and an evidence-backed completed ticket

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
pytest tests/test_sandbox.py tests/test_tasks_export.py tests/test_run_history.py tests/test_job_file_workflow.py tests/test_audit.py -q
```

Expected: all collected tests pass. Report any environment-conditional skips by name and reason; do not summarize skipped checks as passing.

- [ ] **Step 2: Run static repository checks**

Run:

```bash
python -m compileall -q marcedit_web tests
git diff --check a873752..HEAD
```

Expected: both commands exit 0 with no output.

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
pytest -q
```

Expected: all collected tests pass. Record the exact passed and skipped totals plus every skip reason reported by pytest.

- [ ] **Step 4: Request code review**

Use `superpowers:requesting-code-review` against the diff from `a873752` through `HEAD`. The reviewer must check:

- one effective processing limit reaches all three enforcement points;
- injected short limits remain testable and bounded;
- timeout output cannot reach download or version adoption;
- successful output behavior is unchanged;
- user-facing Tasks copy contains no `wall-clock` terminology;
- TASK-156/TASK-157 scope has not leaked into this patch.

Resolve every Critical or Important finding using a fresh red-green cycle. Re-run the focused suite after each correction and the full suite after the final correction. If review has no Critical or Important findings, record that explicitly.

- [ ] **Step 5: Update the ticket with exact verification evidence**

Append an `Implementation Evidence` section that transcribes the exact focused
and full-suite passed/skipped totals from Steps 1 and 3, names every skip reason,
records the static-check outcome, records the code-review outcome and resolved
findings, and confirms the three verified behaviors: the shared 300-second
default, injected short-limit termination, and absence of timeout download or
adoption actions. Replace `Status: In-Progress` with `Status: Completed`; do not
leave two status lines.

- [ ] **Step 6: Commit completion evidence**

```bash
git add .tickets/TASK-155-sandbox-processing-limit.md
git commit -m "docs: complete TASK-155 verification record"
```

- [ ] **Step 7: Verify the final branch state**

Run:

```bash
git status --short
git log --oneline a873752..HEAD
```

Expected: no TASK-155 worktree changes remain. Unrelated pre-existing files must not be staged or committed. The log contains the sandbox-limit implementation, timeout publish gate, any review-fix commits, and the completion-evidence commit.

- [ ] **Step 8: Prepare the production handoff**

Use `superpowers:finishing-a-development-branch`. Present the reviewed commit list, exact test totals and skips, deployment-relevant behavior, and rollback commit. Do not deploy or push to a production host without the user's explicit confirmation at that handoff. TASK-156 begins only after the user accepts TASK-155 in production.
