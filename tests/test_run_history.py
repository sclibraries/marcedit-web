"""Tests for marcedit_web.lib.run_history (TASK-034)."""

from __future__ import annotations

from pathlib import Path

from marcedit_web.lib import run_history
from marcedit_web.lib.run_history import TaskRunRecord, append_run, cleanup_workdirs


def _rec(label: str) -> TaskRunRecord:
    """Build a minimally-populated record for cap tests."""
    return TaskRunRecord(
        timestamp=f"2026-05-25T12:00:0{label}Z",
        user="alice@example.edu",
        input_filename="sample.mrc",
        task_names=["t-" + label],
        input_record_count=7,
        output_record_count=7,
        changed_count=3,
        error_count=0,
    )


def test_append_under_cap_no_eviction():
    history: list[TaskRunRecord] = []
    new, evicted = append_run(history, _rec("0"), cap=5)
    assert len(new) == 1
    assert evicted == []


def test_append_at_cap_no_eviction():
    history = [_rec(str(i)) for i in range(4)]
    new, evicted = append_run(history, _rec("4"), cap=5)
    assert len(new) == 5
    assert evicted == []
    assert [r.timestamp for r in new] == sorted(r.timestamp for r in new)


def test_append_over_cap_evicts_oldest():
    history = [_rec(str(i)) for i in range(5)]
    new, evicted = append_run(history, _rec("5"), cap=5)
    assert len(new) == 5
    assert len(evicted) == 1
    # Oldest (label "0") was evicted; newest (label "5") is at the tail.
    assert evicted[0].task_names == ["t-0"]
    assert new[-1].task_names == ["t-5"]
    # Order preserved across the cut.
    assert [r.task_names[0] for r in new] == [
        "t-1", "t-2", "t-3", "t-4", "t-5",
    ]


def test_append_evicts_multiple_when_history_starts_over_cap():
    """If somehow history is already over cap, append catches up."""
    history = [_rec(str(i)) for i in range(7)]
    new, evicted = append_run(history, _rec("7"), cap=5)
    assert len(new) == 5
    assert len(evicted) == 3
    assert [r.task_names[0] for r in evicted] == ["t-0", "t-1", "t-2"]
    assert new[-1].task_names == ["t-7"]


def test_append_does_not_mutate_input_list():
    """append_run is pure — input list stays unchanged."""
    history = [_rec(str(i)) for i in range(3)]
    snapshot = list(history)
    append_run(history, _rec("3"), cap=5)
    assert history == snapshot


def test_cleanup_workdirs_removes_existing_dirs(tmp_path):
    """Workdir paths on evicted records get removed from disk."""
    work_a = tmp_path / "run_a"
    work_b = tmp_path / "run_b"
    work_a.mkdir()
    work_b.mkdir()
    (work_a / "input.mrc").write_bytes(b"")
    (work_b / "input.mrc").write_bytes(b"")
    records = [
        TaskRunRecord(
            timestamp="t", user="u", input_filename=None,
            workdir=str(work_a),
        ),
        TaskRunRecord(
            timestamp="t", user="u", input_filename=None,
            workdir=str(work_b),
        ),
    ]
    cleanup_workdirs(records)
    assert not work_a.exists()
    assert not work_b.exists()


def test_cleanup_workdirs_ignores_missing(tmp_path):
    """A workdir that's already gone doesn't raise."""
    records = [
        TaskRunRecord(
            timestamp="t", user="u", input_filename=None,
            workdir=str(tmp_path / "never_existed"),
        ),
        TaskRunRecord(
            timestamp="t", user="u", input_filename=None,
            workdir=None,  # explicit None — nothing to clean
        ),
    ]
    cleanup_workdirs(records)  # must not raise
