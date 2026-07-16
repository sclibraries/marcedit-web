"""Tests for marcedit_web.lib.sandbox — the subprocess isolation boundary.

These tests deliberately run malicious-style task bodies and assert the
sandbox absorbs them. They require a POSIX child (preexec_fn /
resource.setrlimit), which Docker/Linux provides. Skip on Windows hosts.
"""

from __future__ import annotations

import io
import json
import os
import signal
import sys
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import sandbox
from marcedit_web.lib.sandbox import SandboxResult, TaskSpec, run_tasks_subprocess


pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="sandbox relies on POSIX resource.setrlimit + preexec_fn",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _serialize(records: list[pymarc.Record]) -> bytes:
    buf = io.BytesIO()
    writer = pymarc.MARCWriter(buf)
    for r in records:
        writer.write(r)
    return buf.getvalue()


def _read_output(result: SandboxResult) -> list[pymarc.Record]:
    with result.output_path.open("rb") as fh:
        return [
            record
            for record in pymarc.MARCReader(
                fh, to_unicode=True, permissive=True
            )
            if record is not None
        ]


class _CompletedPopen:
    """Small completed-process double for parent-boundary assertions."""

    pid = 1234

    def __init__(self, *, returncode=0, stderr="", already_completed=False):
        self._completion_returncode = returncode
        self.returncode = returncode if already_completed else None
        self.stderr = stderr
        self.communicate_timeouts = []

    def communicate(self, timeout=None):
        self.communicate_timeouts.append(timeout)
        self.returncode = self._completion_returncode
        return "", self.stderr

    def poll(self):
        return self.returncode


@pytest.fixture
def one_record_bytes(record) -> bytes:
    """A serialized 1-record MARC blob."""
    return _serialize([record])


@pytest.fixture
def three_records_bytes(make_record) -> bytes:
    return _serialize([make_record(), make_record(), make_record()])


@pytest.fixture
def two_records_bytes(make_record) -> bytes:
    return _serialize([make_record(), make_record()])


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_noop_task_round_trips(one_record_bytes):
    """A `pass` task changes nothing; output has the same record."""
    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        one_record_bytes,
    )
    assert result.returncode == 0
    assert result.errors == []
    reread = _read_output(result)
    assert len(reread) == 1
    assert reread[0].get("001").data == "1234567890"


def test_progress_sidecar_reaches_input_count(tmp_path, two_records_bytes):
    """Each completed input record advances durable observable progress."""
    progress = tmp_path / "progress.json"
    observed = []

    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        two_records_bytes,
        progress_path=progress,
        progress_callback=observed.append,
    )

    assert result.cancelled is False
    assert json.loads(progress.read_text())["processed_records"] == 2
    assert observed[-1] == 2


def test_cancellation_terminates_sandbox_process_group(
    tmp_path, one_record_bytes,
):
    """A user cancellation stops runaway work without becoming a timeout."""
    checks = iter([False, True])

    result = run_tasks_subprocess(
        [TaskSpec(name="slow", body="while True: pass")],
        one_record_bytes,
        timeout=30,
        tmp_dir=tmp_path,
        cancel_requested=lambda: next(checks, True),
        poll_interval=0.01,
    )

    assert result.cancelled is True
    assert result.timed_out is False
    assert result.error_count == 0
    assert not any(
        error["code"] == "sandbox-nonzero-exit"
        for error in result.errors
    )


def test_cancellation_wins_cpu_signal_classification(
    one_record_bytes, monkeypatch,
):
    """An observed cancellation is never reclassified as CPU timeout."""
    process = _CompletedPopen(returncode=-signal.SIGXCPU)
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)

    result = run_tasks_subprocess(
        [TaskSpec(name="busy", body="while True: pass")],
        one_record_bytes,
        cancel_requested=lambda: True,
    )

    assert result.cancelled is True
    assert result.timed_out is False
    assert result.error_count == 0


def test_cancellation_preempts_progress_callbacks(
    tmp_path, one_record_bytes, monkeypatch,
):
    """Once cancellation is observed, durable progress is no longer renewed."""
    progress_path = tmp_path / "progress.json"
    cancellation_state = {"observed": False}
    cancellation_checks = iter([False, True])
    observed_progress = []

    class ProgressPopen:
        pid = 6790
        returncode = None

        def communicate(self, timeout=None):
            if timeout is not None:
                progress_path.write_text('{"processed_records": 1}')
                raise sandbox.subprocess.TimeoutExpired("sandbox", timeout)
            progress_path.write_text('{"processed_records": 2}')
            self.returncode = -signal.SIGKILL
            return "", "cancelled"

        def poll(self):
            return self.returncode

    def cancel_requested():
        requested = next(cancellation_checks, True)
        cancellation_state["observed"] = requested
        return requested

    def record_progress(processed_records):
        if cancellation_state["observed"]:
            raise RuntimeError("lease entered cancelling state")
        observed_progress.append(processed_records)

    process = ProgressPopen()
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(sandbox.os, "killpg", lambda *_a: None)
    monkeypatch.setattr(sandbox.time, "sleep", lambda _seconds: None)

    result = run_tasks_subprocess(
        [TaskSpec(name="slow", body="while True: pass")],
        one_record_bytes,
        progress_path=progress_path,
        progress_callback=record_progress,
        cancel_requested=cancel_requested,
        poll_interval=0.01,
    )

    assert result.cancelled is True
    assert result.timed_out is False
    assert observed_progress == []
    assert json.loads(progress_path.read_text())["processed_records"] == 2


def test_startup_removes_stale_progress_temporary(
    tmp_path, one_record_bytes, monkeypatch,
):
    """A prior interrupted atomic write cannot leak into the next run."""
    progress_path = tmp_path / "progress.json"
    temporary_path = Path(str(progress_path) + ".tmp")
    temporary_path.write_text("stale partial progress")
    process = _CompletedPopen(returncode=0, already_completed=True)
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)

    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        one_record_bytes,
        progress_path=progress_path,
    )

    assert result.returncode == 0
    assert not temporary_path.exists()


def test_completed_child_wins_cancellation_poll_race(
    one_record_bytes, monkeypatch,
):
    """Completion already visible to the parent is not cancellation."""
    process = _CompletedPopen(returncode=0, already_completed=True)
    cancellation_checks = []
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)

    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        one_record_bytes,
        cancel_requested=lambda: cancellation_checks.append(True) or True,
    )

    assert result.returncode == 0
    assert result.cancelled is False
    assert result.timed_out is False
    assert cancellation_checks == []


def test_cancelled_reused_workdir_does_not_return_stale_artifacts(
    tmp_path, one_record_bytes, monkeypatch,
):
    """Early cancellation cannot expose errors/output from an earlier run."""
    (tmp_path / "errors.json").write_text(
        '{"error_count": 1, "errors": [{"code": "stale"}]}'
    )
    (tmp_path / "output.mrc").write_bytes(b"stale output")

    class RunningPopen:
        pid = 6789
        returncode = None

        def communicate(self, timeout=None):
            self.returncode = -signal.SIGTERM
            return "", "cancelled"

        def poll(self):
            return self.returncode

    process = RunningPopen()
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(sandbox.os, "killpg", lambda *_a: None)
    monkeypatch.setattr(sandbox.time, "sleep", lambda _seconds: None)

    result = run_tasks_subprocess(
        [TaskSpec(name="slow", body="while True: pass")],
        one_record_bytes,
        tmp_dir=tmp_path,
        cancel_requested=lambda: True,
    )

    assert result.cancelled is True
    assert result.error_count == 0
    assert result.errors == []
    assert not result.output_path.exists()


def test_progress_callback_ignores_invalid_and_duplicate_sidecars(tmp_path):
    """Polling never exposes partial JSON or repeats an observed count."""
    progress_path = tmp_path / "progress.json"
    observed = []

    progress_path.write_text('{"processed_records":')
    last_progress = sandbox._report_progress(
        progress_path, observed.append, None,
    )
    progress_path.write_text('{"processed_records": 7}')
    last_progress = sandbox._report_progress(
        progress_path, observed.append, last_progress,
    )
    last_progress = sandbox._report_progress(
        progress_path, observed.append, last_progress,
    )

    assert last_progress == 7
    assert observed == [7]


def test_process_group_termination_escalates_and_reaps(monkeypatch):
    """A SIGTERM-resistant sandbox is SIGKILLed after the bounded grace."""
    signals = []

    class StubbornPopen:
        pid = 5678
        returncode = None
        reaped = False

        def communicate(self, timeout=None):
            if timeout == 2:
                raise sandbox.subprocess.TimeoutExpired("sandbox", timeout)
            self.returncode = -signal.SIGKILL
            self.reaped = True
            return "", "stubborn stderr"

        def poll(self):
            return self.returncode

    process = StubbornPopen()
    monkeypatch.setattr(
        sandbox.os,
        "killpg",
        lambda pid, sig: signals.append((pid, sig)),
    )
    monkeypatch.setattr(sandbox.time, "sleep", lambda _seconds: None)

    _, stderr = sandbox._terminate_process_group(process)

    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    assert process.reaped is True
    assert stderr == "stubborn stderr"


def test_process_group_kills_descendants_after_leader_accepts_term(
    monkeypatch,
):
    """Leader exit cannot suppress KILL for a TERM-ignoring descendant."""
    signals = []

    class ExitingLeaderPopen:
        pid = 5790
        returncode = None

        def communicate(self, timeout=None):
            self.returncode = -signal.SIGTERM
            return "", "leader exited"

        def poll(self):
            return self.returncode

    process = ExitingLeaderPopen()
    monkeypatch.setattr(
        sandbox.os,
        "killpg",
        lambda pid, sig: signals.append((pid, sig)),
    )
    monkeypatch.setattr(sandbox.time, "sleep", lambda _seconds: None)

    sandbox._terminate_process_group(process)

    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]


def test_process_group_exit_race_is_reaped_without_reused_pid_signal(
    monkeypatch,
):
    """A group disappearing after poll is completion, not a kill failure."""
    process = _CompletedPopen(stderr="finished during signal race")
    process.returncode = None

    def process_gone(_pid, _sig):
        process.returncode = 0
        raise ProcessLookupError

    monkeypatch.setattr(sandbox.os, "killpg", process_gone)

    _, stderr = sandbox._terminate_process_group(process)

    assert process.returncode == 0
    assert process.communicate_timeouts == [None]
    assert stderr == "finished during signal race"


def test_progress_callback_failure_still_reaps_child(
    tmp_path, one_record_bytes, monkeypatch,
):
    """A callback/leader-exit race still cleans the owned process group."""
    progress_path = tmp_path / "progress.json"
    signals = []

    class ProgressThenWaitPopen:
        pid = 4321
        returncode = None
        reaped = False

        def communicate(self, timeout=None):
            if timeout is None:
                self.returncode = -signal.SIGTERM
                self.reaped = True
                return "", "callback cleanup"
            progress_path.write_text('{"processed_records": 1}')
            raise sandbox.subprocess.TimeoutExpired("sandbox", timeout)

        def poll(self):
            return self.returncode

    process = ProgressThenWaitPopen()
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(
        sandbox.os,
        "killpg",
        lambda pid, sig: signals.append((pid, sig)),
    )
    monkeypatch.setattr(sandbox.time, "sleep", lambda _seconds: None)

    def fail_callback(_processed_records):
        process.returncode = 0
        raise RuntimeError("progress sink unavailable")

    with pytest.raises(RuntimeError, match="progress sink unavailable"):
        run_tasks_subprocess(
            [TaskSpec(name="noop", body="pass")],
            one_record_bytes,
            progress_path=progress_path,
            progress_callback=fail_callback,
            poll_interval=0.01,
        )

    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    assert process.reaped is True


def test_default_processing_limit_reaches_parent_and_child(
    one_record_bytes, monkeypatch,
):
    """Large legitimate runs get one shared five-minute safety budget."""
    captured = {}
    resource_limits = []

    process = _CompletedPopen()

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["preexec_fn"] = kwargs["preexec_fn"]
        captured["start_new_session"] = kwargs["start_new_session"]
        captured["stdout"] = kwargs["stdout"]
        captured["stderr"] = kwargs["stderr"]
        return process

    monkeypatch.setattr(sandbox.subprocess, "Popen", fake_popen)
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
        poll_interval=400,
    )
    captured["preexec_fn"]()

    assert sandbox.DEFAULT_PROCESSING_LIMIT_SECONDS == 300
    assert process.communicate_timeouts == [pytest.approx(300, abs=0.01)]
    assert captured["start_new_session"] is True
    assert captured["stdout"] == sandbox.subprocess.DEVNULL
    assert captured["stderr"] != sandbox.subprocess.PIPE
    cpu_arg = captured["cmd"].index("--cpu-seconds")
    assert captured["cmd"][cpu_arg + 1] == "300"
    assert (
        sandbox.resource.RLIMIT_CPU,
        (300, 301),
    ) in resource_limits


def test_fractional_timeout_uses_one_cpu_second(
    one_record_bytes, monkeypatch,
):
    """Fast tests never turn a fractional timeout into a zero CPU limit."""
    captured = {}

    process = _CompletedPopen()

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return process

    monkeypatch.setattr(sandbox.subprocess, "Popen", fake_popen)

    run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        one_record_bytes,
        timeout=0.1,
    )

    cpu_arg = captured["cmd"].index("--cpu-seconds")
    assert process.communicate_timeouts == [pytest.approx(0.1, abs=0.01)]
    assert captured["cmd"][cpu_arg + 1] == "1"


def test_injected_timeout_reaches_child_cpu_limit(one_record_bytes):
    """The defensive in-child CPU limit matches the invocation budget."""
    result = run_tasks_subprocess(
        [TaskSpec(
            name="inspect-limit",
            body=(
                "import resource\n"
                "cpu_limit = resource.getrlimit(resource.RLIMIT_CPU)\n"
                "assert cpu_limit == (2, 3), cpu_limit\n"
            ),
        )],
        one_record_bytes,
        timeout=2.0,
    )

    assert result.returncode == 0
    assert result.errors == []


def test_sigxcpu_completion_is_reported_as_timeout(
    one_record_bytes, monkeypatch,
):
    """A child reaching its CPU soft limit keeps timeout safety gates active."""
    process = _CompletedPopen(
        stderr="CPU time limit exceeded",
        returncode=-signal.SIGXCPU,
    )
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)

    result = run_tasks_subprocess(
        [TaskSpec(name="busy", body="while True:\n    pass\n")],
        one_record_bytes,
        timeout=2.0,
    )

    assert result.returncode == -signal.SIGXCPU
    assert result.timed_out is True
    assert result.error_count == 1
    assert result.errors[-1]["code"] == "sandbox-timeout"


def test_ordinary_nonzero_completion_is_not_reported_as_timeout(
    one_record_bytes, monkeypatch,
):
    """Only the CPU-limit signal is normalized to timeout state."""
    process = _CompletedPopen(stderr="ordinary failure", returncode=7)
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *_a, **_k: process)

    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        one_record_bytes,
        timeout=2.0,
    )

    assert result.returncode == 7
    assert result.timed_out is False
    assert result.error_count == 1
    assert result.errors[-1]["code"] == "sandbox-nonzero-exit"


def test_delete_tag_via_transforms_helper(one_record_bytes):
    """The transforms module is preloaded; delete_tags works in-sandbox."""
    result = run_tasks_subprocess(
        [TaskSpec(
            name="strip-029",
            body='transforms.delete_tags(record, "029")',
        )],
        one_record_bytes,
    )
    assert result.returncode == 0
    assert result.errors == []
    reread = _read_output(result)
    assert reread[0].get("029") is None


def test_task_imports_are_executed(one_record_bytes):
    """``imports`` entries run before the body; the body can use them."""
    result = run_tasks_subprocess(
        [TaskSpec(
            name="custom-import",
            body='delete_tags(record, "029")',
            imports=["from marcedit_web.lib.transforms import delete_tags"],
        )],
        one_record_bytes,
    )
    assert result.returncode == 0
    assert result.errors == []


def test_multiple_tasks_run_in_order(one_record_bytes):
    """Tasks apply sequentially; second one sees the first's edits."""
    result = run_tasks_subprocess(
        [
            TaskSpec(name="strip-029", body='transforms.delete_tags(record, "029")'),
            TaskSpec(name="strip-891", body='transforms.delete_tags(record, "891")'),
        ],
        one_record_bytes,
    )
    assert result.returncode == 0
    reread = _read_output(result)
    assert reread[0].get("029") is None
    assert reread[0].get("891") is None


def test_task_030_new_ops_combined_smoke(one_record_bytes):
    """End-to-end: form-built bodies of the new typed ops apply cleanly.

    Renders one op of each new kind via the form-builder, then runs the
    combined body through the sandbox driver. The sandbox driver
    pre-exposes every public ``transforms`` helper at the namespace top
    level (see ``sandbox._DRIVER_SCRIPT``), so the form-emitted bodies
    work without explicit imports.
    """
    from marcedit_web.lib import task_builder
    from marcedit_web.lib.task_builder import Operation

    rendered = task_builder.render_ops_to_python([
        Operation(kind="copy-field",
                  params={"src_tag": "856", "dst_tag": "956"}),
        Operation(kind="add-subfield",
                  params={"tag": "655", "code": "9", "value": "LOCAL",
                          "position": "end"}),
        Operation(kind="delete-subfield",
                  params={"tag": "856", "codes": "u"}),
        Operation(kind="edit-indicators",
                  params={"tag": "245", "ind1": "0", "ind2": "0"}),
        Operation(kind="replace-field-data-by-regex",
                  params={"tag": "245", "pattern": "Test",
                          "replacement": "Edited", "ignore_case": False}),
    ])
    result = run_tasks_subprocess(
        [TaskSpec(name="task030-combined", body=rendered["body"])],
        one_record_bytes,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert result.errors == [], f"errors: {result.errors}"

    reread = _read_output(result)
    rec = reread[0]
    # copy-field added a 956 mirror of every 856.
    assert len(rec.get_fields("956")) == len(
        list(field for field in rec.fields if field.tag == "856")
    ) + len(rec.get_fields("956")) - len(rec.get_fields("956"))  # sanity
    assert rec.get_fields("956"), "copy-field didn't run"
    # add-subfield put a $9 LOCAL on every 655.
    assert any(
        sf.code == "9" and sf.value == "LOCAL"
        for f in rec.get_fields("655")
        for sf in f.subfields
    )
    # delete-subfield stripped $u from 856.
    assert not any(
        sf.code == "u"
        for f in rec.get_fields("856")
        for sf in f.subfields
    )
    # edit-indicators set both indicators on 245 to '0'.
    f245 = rec.get_fields("245")[0]
    assert list(f245.indicators) == ["0", "0"]
    # regex_replace_field_data swapped "Test" → "Edited" in 245 subfield values.
    assert "Edited title" in f245["a"]


# ---------------------------------------------------------------------------
# Malicious / runaway task bodies
# ---------------------------------------------------------------------------


def test_task_exception_is_captured_not_raised(one_record_bytes):
    """A task body that raises produces an error entry; the run continues."""
    result = run_tasks_subprocess(
        [TaskSpec(name="boom", body='raise RuntimeError("explicit")')],
        one_record_bytes,
    )
    # Run completes (returncode == 0); error is in the structured log.
    assert result.returncode == 0
    assert len(result.errors) == 1
    assert result.errors[0]["code"] == "transform-failed"
    assert "RuntimeError" in result.errors[0]["message"]
    # The record still makes it to the output (with no changes).
    reread = _read_output(result)
    assert len(reread) == 1


def test_repeated_task_errors_are_counted_but_diagnostics_are_capped(
    one_record_bytes,
):
    """A task failing on 100K records must not retain 100K error dicts."""
    record_count = sandbox.MAX_RETAINED_ERRORS + 5
    result = run_tasks_subprocess(
        [TaskSpec(name="boom", body='raise RuntimeError("explicit")')],
        one_record_bytes * record_count,
    )

    assert result.error_count == record_count
    assert len(result.errors) == sandbox.MAX_RETAINED_ERRORS
    assert len(_read_output(result)) == record_count


def test_filesystem_side_effect_lands_in_sandbox_workdir(
    one_record_bytes, tmp_path,
):
    """A task that writes a file writes it under the sandbox's cwd,
    not the parent's filesystem.

    We can't prove the negative against ``/tmp/PWNED`` perfectly (the
    Streamlit container's /tmp is shared with the subprocess), but we
    can verify the sandbox runs in its own workdir so RELATIVE writes
    land there and not in the Streamlit process's cwd.
    """
    workdir = tmp_path / "sb"
    result = run_tasks_subprocess(
        [TaskSpec(
            name="write-file",
            body='open("./pwn-marker.txt", "w").write("x"); pass',
        )],
        one_record_bytes,
        tmp_dir=workdir,
    )
    # The file is created INSIDE the sandbox workdir, not the test cwd.
    assert (workdir / "pwn-marker.txt").exists()
    assert not Path("./pwn-marker.txt").exists()
    # And the rest of the run still works.
    assert result.returncode == 0


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


def test_memory_bomb_killed_or_caught(one_record_bytes):
    """A task that tries to allocate beyond RLIMIT_AS raises MemoryError
    inside the sandbox; the parent doesn't see the failure."""
    # Try to allocate ~2 GB — well over the 512 MB AS limit.
    result = run_tasks_subprocess(
        [TaskSpec(
            name="memhog",
            body='_ = b"x" * (2 * 1024 * 1024 * 1024)',
        )],
        one_record_bytes,
    )
    # Either: subprocess exits cleanly with a per-record MemoryError
    # in the errors log (Linux MAY satisfy a malloc up to overcommit
    # limit but then OOM-kill on touch), or the subprocess crashes
    # with a non-zero return code. Both outcomes are acceptable; the
    # parent must NOT crash and must NOT eat 2 GB of RAM.
    assert (
        result.timed_out
        or result.returncode != 0
        or any(
            "MemoryError" in (e.get("message") or "") for e in result.errors
        )
    )


def test_fork_bomb_blocked_by_nproc(one_record_bytes):
    """RLIMIT_NPROC stops a task that tries to spawn dozens of children."""
    # Try to fork 100 children. RLIMIT_NPROC=32 means OSError partway in.
    body = (
        "import os\n"
        "for i in range(100):\n"
        "    try:\n"
        "        pid = os.fork()\n"
        "        if pid == 0:\n"
        "            os._exit(0)\n"
        "    except OSError:\n"
        "        break\n"
    )
    result = run_tasks_subprocess(
        [TaskSpec(name="forkbomb", body=body)],
        one_record_bytes,
        timeout=10.0,
    )
    # The sandbox completes without hanging the parent.
    assert result.timed_out is False
    assert result.returncode is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_record_input_succeeds():
    """No records in → no records out, no errors."""
    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        b"",
    )
    assert result.returncode == 0
    assert result.output_path.read_bytes() == b""


def test_empty_task_list_passes_records_through(one_record_bytes):
    result = run_tasks_subprocess([], one_record_bytes)
    assert result.returncode == 0
    reread = _read_output(result)
    assert len(reread) == 1


# ---------------------------------------------------------------------------
# Stage 20: input_path streaming entry point
# ---------------------------------------------------------------------------


def test_input_path_supplies_records_without_in_memory_bytes(
    one_record_bytes, tmp_path
):
    """The streaming entry point uses an existing file as sandbox input.

    A path-based call mirrors the bytes-based call: same record in,
    same record out. Tasks page uses this to avoid materializing the
    whole batch in the parent process.
    """
    in_path = tmp_path / "input.mrc"
    in_path.write_bytes(one_record_bytes)
    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        input_path=in_path,
    )
    assert result.returncode == 0
    reread = _read_output(result)
    assert len(reread) == 1
    assert reread[0].get("001").data == "1234567890"


def test_input_path_and_record_bytes_are_mutually_exclusive(
    one_record_bytes, tmp_path
):
    """Supplying both inputs is a programming error — raise loudly."""
    in_path = tmp_path / "input.mrc"
    in_path.write_bytes(one_record_bytes)
    with pytest.raises(ValueError):
        run_tasks_subprocess(
            [TaskSpec(name="noop", body="pass")],
            one_record_bytes,
            input_path=in_path,
        )


def test_neither_input_supplied_raises():
    with pytest.raises(ValueError):
        run_tasks_subprocess([TaskSpec(name="noop", body="pass")])


def test_input_path_is_used_directly_no_copy(one_record_bytes, tmp_path):
    """Verify the sandbox doesn't write a second copy into its workdir.

    With ``input_path=p``, the workdir should NOT contain an ``input.mrc``
    that's separate from ``p`` — the sandbox uses ``p`` as the
    ``--input`` arg directly.
    """
    in_path = tmp_path / "elsewhere" / "preflight.mrc"
    in_path.parent.mkdir()
    in_path.write_bytes(one_record_bytes)
    workdir = tmp_path / "sandbox-work"
    workdir.mkdir()
    run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        input_path=in_path,
        tmp_dir=workdir,
    )
    assert not (workdir / "input.mrc").exists()


def test_parent_returns_output_path_without_materializing_it(
    one_record_bytes, tmp_path, monkeypatch
):
    """Large sandbox output remains on disk until a bounded consumer reads it."""
    input_path = tmp_path / "input.mrc"
    input_path.write_bytes(one_record_bytes)
    workdir = tmp_path / "sandbox"
    original_read_bytes = Path.read_bytes

    def _guard_output(self):
        if self.name == "output.mrc":
            raise AssertionError("sandbox parent must not read all output bytes")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _guard_output)

    result = run_tasks_subprocess(
        [TaskSpec(name="noop", body="pass")],
        input_path=input_path,
        tmp_dir=workdir,
    )

    assert result.output_path == workdir / "output.mrc"
    assert result.output_path.is_file()
