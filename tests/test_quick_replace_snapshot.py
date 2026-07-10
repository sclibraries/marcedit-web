"""Quick find/replace apply must record a job snapshot (TASK-143).

The History timeline is built from provenance snapshots; before this
change, quick find/replace was the only mutating flow that did not
snapshot, so its changes were invisible in History.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pymarc

from marcedit_web.lib.record_store import RecordStore


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self.rerun_called = False

    def error(self, message):
        self.errors.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def warning(self, message):
        self.warnings.append(str(message))

    def caption(self, message):
        self.captions.append(str(message))

    def rerun(self):
        self.rerun_called = True


def _record(title: str) -> pymarc.Record:
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(tag="001", data="qr-snap"))
    record.add_field(
        pymarc.Field(
            tag="245",
            indicators=["0", "0"],
            subfields=[pymarc.Subfield(code="a", value=title)],
        )
    )
    return record


def _store(tmp_path) -> RecordStore:
    return RecordStore.from_records(
        [_record("Old title")],
        tmp_dir=tmp_path / "records",
        filename="qr.mrc",
    )


def _tasks_render(monkeypatch, fake_st):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    return tasks_render


def _preview():
    return SimpleNamespace(
        request=SimpleNamespace(
            tag="245", subfield="a", regex=False, ignore_case=False
        ),
        matched_count=1,
        changed_count=1,
    )


def _wire(monkeypatch, tasks_render, store, snapshots):
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.session, "current_filename", lambda: "qr.mrc"
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *a, **k: None)

    def fake_apply(store_arg, preview_arg):
        store_arg.replace(0, _record("New title"))
        store_arg.persist_to_disk()
        return SimpleNamespace(error=None, applied_count=1)

    monkeypatch.setattr(
        tasks_render.batch_replace, "apply_preview", fake_apply
    )

    def fake_snapshot(**kwargs):
        snapshots.append(
            {
                **kwargs,
                "captured_before": Path(kwargs["before_path"]).read_bytes(),
                "captured_after": Path(kwargs["after_path"]).read_bytes(),
            }
        )
        return {"id": 7, "job_id": 3, "kind": kwargs["kind"]}

    monkeypatch.setattr(
        tasks_render.snapshot_actions, "record_job_snapshot", fake_snapshot
    )


def test_apply_records_quick_replace_snapshot(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    snapshots: list[dict] = []
    _wire(monkeypatch, tasks_render, store, snapshots)
    fake_st.session_state["current_job_id"] = 3

    tasks_render._apply_quick_preview(_preview())

    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap["kind"] == "quick-replace"
    assert snap["job_id"] == 3
    assert snap["label"] == "Find/replace 245$a"
    # before captured pre-apply, after captured post-apply
    assert b"Old title" in snap["captured_before"]
    assert b"New title" in snap["captured_after"]
    assert "before_bytes" not in snap
    assert "after_bytes" not in snap
    assert snap["summary"]["changed_count"] == 1
    assert fake_st.successes  # apply still reports success


def test_snapshot_failure_does_not_block_apply(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    snapshots: list[dict] = []
    _wire(monkeypatch, tasks_render, store, snapshots)
    fake_st.session_state["current_job_id"] = 3

    def boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(
        tasks_render.snapshot_actions, "record_job_snapshot", boom
    )

    tasks_render._apply_quick_preview(_preview())

    assert fake_st.successes  # apply completed
    assert fake_st.warnings  # failure surfaced, not hidden
    assert fake_st.rerun_called
