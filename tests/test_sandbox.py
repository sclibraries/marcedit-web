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
from types import SimpleNamespace

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
    reread = _read_output(result)
    assert len(reread) == 1
    assert reread[0].get("001").data == "1234567890"


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
