"""Quick find/replace acceptance creates immutable file versions."""

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
        store_id=None,
        store_revision=0,
    )


def _wire(monkeypatch, tasks_render, store, adoptions):
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

    monkeypatch.setattr(
        tasks_render.session,
        "adopt_current_candidate",
        lambda **kwargs: adoptions.append({
            **kwargs,
            "candidate_bytes": Path(kwargs["candidate_path"]).read_bytes(),
        }) or {"version_number": 2},
    )


def test_apply_quick_replace_adopts_candidate_without_mutating_current(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    adoptions: list[dict] = []
    _wire(monkeypatch, tasks_render, store, adoptions)
    fake_st.session_state.update({
        "current_job_id": 3,
        "job_file_id": 4,
        "job_file_version_id": 1,
    })
    before = store.path.read_bytes()
    preview = _preview()
    preview.store_id = id(store)

    tasks_render._apply_quick_preview(preview)

    assert store.path.read_bytes() == before
    assert len(adoptions) == 1
    adoption = adoptions[0]
    assert adoption["source_kind"] == "quick-replace"
    assert adoption["label"] == "Find/replace 245$a"
    assert b"New title" in adoption["candidate_bytes"]
    assert adoption["summary"]["changed_count"] == 1
    assert fake_st.successes


def test_quick_replace_adoption_failure_preserves_current(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    adoptions: list[dict] = []
    _wire(monkeypatch, tasks_render, store, adoptions)
    fake_st.session_state.update({
        "current_job_id": 3,
        "job_file_id": 4,
        "job_file_version_id": 1,
    })
    before = store.path.read_bytes()
    preview = _preview()
    preview.store_id = id(store)

    def boom(**kwargs):
        raise tasks_render.job_files.JobFileError("file changed since preview")

    monkeypatch.setattr(
        tasks_render.session, "adopt_current_candidate", boom
    )

    tasks_render._apply_quick_preview(preview)

    assert store.path.read_bytes() == before
    assert fake_st.errors == ["file changed since preview"]
    assert not fake_st.successes


def test_quick_replace_rejects_preview_for_an_older_store(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    adoptions = []
    _wire(monkeypatch, tasks_render, store, adoptions)
    fake_st.session_state.update({
        "job_file_id": 4,
        "job_file_version_id": 2,
    })
    preview = _preview()
    preview.store_id = id(object())

    tasks_render._apply_quick_preview(preview)

    assert fake_st.errors == ["Batch changed since preview."]
    assert adoptions == []


def test_quick_load_retains_in_place_replace_and_snapshot(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    adoptions = []
    _wire(monkeypatch, tasks_render, store, adoptions)
    snapshots = []
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **kwargs: snapshots.append(kwargs),
    )
    fake_st.session_state.update({
        "current_job_id": 3,
        "job_file_id": None,
        "job_file_version_id": None,
        "quick_load_mode": True,
    })
    preview = _preview()
    preview.store_id = id(store)

    tasks_render._apply_quick_preview(preview)

    assert b"New title" in store.path.read_bytes()
    assert len(snapshots) == 1
    assert adoptions == []
