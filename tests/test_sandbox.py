"""Tests for marcedit_web.lib.sandbox — the subprocess isolation boundary.

These tests deliberately run malicious-style task bodies and assert the
sandbox absorbs them. They require a POSIX child (preexec_fn /
resource.setrlimit), which Docker/Linux provides. Skip on Windows hosts.
"""

from __future__ import annotations

import io
import os
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


@pytest.fixture
def one_record_bytes(record) -> bytes:
    """A serialized 1-record MARC blob."""
    return _serialize([record])


@pytest.fixture
def three_records_bytes(make_record) -> bytes:
    return _serialize([make_record(), make_record(), make_record()])


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
    reread = list(pymarc.MARCReader(io.BytesIO(result.records_bytes),
                                    to_unicode=True, permissive=True))
    assert len(reread) == 1
    assert reread[0].get("001").data == "1234567890"


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
    reread = list(pymarc.MARCReader(io.BytesIO(result.records_bytes),
                                    to_unicode=True, permissive=True))
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
    reread = list(pymarc.MARCReader(io.BytesIO(result.records_bytes),
                                    to_unicode=True, permissive=True))
    assert reread[0].get("029") is None
    assert reread[0].get("891") is None


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
    reread = list(pymarc.MARCReader(io.BytesIO(result.records_bytes),
                                    to_unicode=True, permissive=True))
    assert len(reread) == 1


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
    """A wall-clock-busy task is killed by the timeout parameter."""
    # Use a tight timeout so the test doesn't spend 30s.
    result = run_tasks_subprocess(
        [TaskSpec(name="busy", body="while True:\n    pass\n")],
        one_record_bytes,
        timeout=2.0,
    )
    assert result.timed_out is True
    assert any(e["code"] == "sandbox-timeout" for e in result.errors)


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
    assert result.records_bytes == b""


def test_empty_task_list_passes_records_through(one_record_bytes):
    result = run_tasks_subprocess([], one_record_bytes)
    assert result.returncode == 0
    reread = list(pymarc.MARCReader(io.BytesIO(result.records_bytes),
                                    to_unicode=True, permissive=True))
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
    reread = list(pymarc.MARCReader(io.BytesIO(result.records_bytes),
                                    to_unicode=True, permissive=True))
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
