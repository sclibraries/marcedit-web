"""Render-helper tests for Tasks-page quick batch operations (TASK-137)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pymarc

from marcedit_web.lib.quick_batch import QuickBatchRequest
from marcedit_web.lib.record_store import RecordStore


class _Spinner:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Progress:
    def __init__(self, st: "_FakeStreamlit"):
        self._st = st

    def progress(self, value):
        self._st.progress_updates.append(value)

    def empty(self):
        self._st.progress_cleared += 1


class _Status:
    def __init__(self, st: "_FakeStreamlit"):
        self._st = st

    def markdown(self, message):
        self._st.status_messages.append(str(message))

    def empty(self):
        self._st.status_cleared += 1


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.captions: list[str] = []
        self.markdowns: list[str] = []
        self.buttons: list[dict] = []
        self.clicked_keys: set[str] = set()
        self.download_buttons: list[dict] = []
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.spinners: list[str] = []
        self.progress_updates: list[float] = []
        self.progress_cleared = 0
        self.status_messages: list[str] = []
        self.status_cleared = 0
        self.rerun_called = False

    def error(self, message):
        self.errors.append(str(message))

    def caption(self, message):
        self.captions.append(str(message))

    def markdown(self, message):
        self.markdowns.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return kwargs.get("key") in self.clicked_keys

    def spinner(self, message):
        self.spinners.append(str(message))
        return _Spinner()

    def progress(self, value):
        self.progress_updates.append(value)
        return _Progress(self)

    def empty(self):
        return _Status(self)

    def download_button(self, **kwargs):
        self.download_buttons.append(kwargs)

    def rerun(self):
        self.rerun_called = True


def _record():
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(tag="001", data="quick-batch-ui"))
    return record


def _store(tmp_path):
    return RecordStore.from_records(
        [_record()],
        tmp_dir=tmp_path / "records",
        filename="quick-ui.mrc",
    )


def _tasks_render(monkeypatch, fake_st):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    return tasks_render


def test_quick_batch_preview_stores_non_mutating_preview(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)

    request = QuickBatchRequest(kind="leader", position="05", value="c")
    tasks_render._build_and_store_quick_batch_preview(request)

    preview = fake_st.session_state[tasks_render._K_QB_PREVIEW]
    assert preview.changed_count == 1
    assert str(preview.output_records[0].leader)[5] == "c"
    assert str(store.get(0).leader)[5] == "n"
    assert fake_st.progress_updates == [0.0, 1.0]
    assert fake_st.status_messages == ["Previewing record 1 of 1…"]
    assert fake_st.progress_cleared == 1
    assert fake_st.status_cleared == 1


def test_quick_batch_preview_clears_quick_find_replace_preview(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    fake_st.session_state[tasks_render._K_BR_PREVIEW] = object()
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)

    request = QuickBatchRequest(kind="leader", position="05", value="c")
    tasks_render._build_and_store_quick_batch_preview(request)

    assert tasks_render._K_BR_PREVIEW not in fake_st.session_state
    assert tasks_render._K_QB_PREVIEW in fake_st.session_state


def test_quick_batch_progress_callback_is_throttled(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)

    callback, progress, status = tasks_render._quick_batch_progress(
        "Previewing",
        min_step=200,
    )
    for processed in range(1, 1001):
        callback(processed, 1000)
    progress.empty()
    status.empty()

    assert fake_st.status_messages == [
        "Previewing record 1 of 1,000…",
        "Previewing record 200 of 1,000…",
        "Previewing record 400 of 1,000…",
        "Previewing record 600 of 1,000…",
        "Previewing record 800 of 1,000…",
        "Previewing record 1,000 of 1,000…",
    ]
    assert fake_st.progress_updates == [0.0, 0.001, 0.2, 0.4, 0.6, 0.8, 1.0]


def test_quick_batch_apply_mutates_store_clears_cache_and_audits(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    fake_st.session_state["issues_cache"] = {"stale": object()}
    fake_st.session_state["current_job_id"] = 42
    stale_export = tmp_path / "stale-export.mrc"
    stale_export.write_bytes(b"stale")
    fake_st.session_state["quick_batch_export"] = {
        "filename": "stale.mrc",
        "path": str(stale_export),
        "snapshot_id": None,
        "temporary": True,
    }
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    events: list[dict] = []
    snapshots: list[dict] = []

    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render.session, "current_user_id", lambda: "cataloger")
    monkeypatch.setattr(tasks_render.session, "current_filename", lambda: "quick-ui.mrc")
    def fake_audit_event(kind, **payload):
        events.append({"event": kind, **payload})

    monkeypatch.setattr(tasks_render, "audit_event", fake_audit_event)
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **kwargs: snapshots.append(kwargs) or {
            "id": 7,
            "job_id": kwargs["job_id"],
            "kind": kwargs["kind"],
        },
    )

    request = QuickBatchRequest(kind="leader", position="05", value="c")
    preview = tasks_render.quick_batch.build_preview(store, request)
    fake_st.session_state[tasks_render._K_QB_PREVIEW] = preview

    tasks_render._apply_quick_batch_preview(preview)

    assert str(store.get(0).leader)[5] == "c"
    assert fake_st.session_state["issues_cache"] == {}
    assert tasks_render._K_QB_PREVIEW not in fake_st.session_state
    export = fake_st.session_state[tasks_render._K_QB_EXPORT]
    assert export["filename"].startswith("quick-ui_quickbatch_")
    assert export["filename"].endswith(".mrc")
    assert export["filename"] != "quick-ui.mrc"
    assert "data" not in export
    assert Path(export["path"]).exists()
    assert export["temporary"] is True
    assert export["snapshot_id"] == 7
    assert not stale_export.exists()
    assert snapshots[0]["kind"] == "quick-batch"
    assert snapshots[0]["label"] == "Leader value"
    assert snapshots[0]["summary"]["operation_kind"] == "leader"
    assert events == [
        {
            "event": "job-snapshot-created",
            "user": "cataloger",
            "snapshot_id": 7,
            "job_id": 42,
            "snapshot_kind": "quick-batch",
        },
        {
            "event": "quick-batch-applied",
            "user": "cataloger",
            "filename": "quick-ui.mrc",
            "operation_kind": "leader",
            "changed_count": 1,
            "skipped_count": 0,
        }
    ]
    assert fake_st.successes == ["Applied quick batch operation to 1 record(s)."]
    assert fake_st.spinners == [
        "Applying quick batch operation to 1 record…"
    ]
    assert fake_st.progress_updates == [0.0, 1.0]
    assert fake_st.status_messages == ["Checking record 1 of 1…"]
    assert fake_st.progress_cleared == 1
    assert fake_st.status_cleared == 1
    assert fake_st.rerun_called is True


def test_render_quick_batch_export_shows_download_and_history_location(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    export_path = tmp_path / "quick-ui-export.mrc"
    export_path.write_bytes(b"updated")
    fake_st.session_state[tasks_render._K_QB_EXPORT] = {
        "filename": "quick-ui_quickbatch_20260709_190000.mrc",
        "path": str(export_path),
        "snapshot_id": 7,
    }

    tasks_render._render_quick_batch_export()

    assert fake_st.markdowns == ["**Updated batch is loaded in this session.**"]
    assert fake_st.captions == [
        "Rollback and before/after downloads are available on the History page."
    ]
    assert fake_st.download_buttons == []
    assert fake_st.session_state.get("quick_batch_download_ready") is None


def test_render_quick_batch_export_download_reads_path_only_after_prepare(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    fake_st.session_state["quick_batch_download_ready"] = True
    tasks_render = _tasks_render(monkeypatch, fake_st)
    export_path = tmp_path / "quick-ui-export-ready.mrc"
    export_path.write_bytes(b"updated")
    fake_st.session_state[tasks_render._K_QB_EXPORT] = {
        "filename": "quick-ui_quickbatch_20260709_190000.mrc",
        "path": str(export_path),
        "snapshot_id": 7,
    }

    tasks_render._render_quick_batch_export()

    assert fake_st.download_buttons == [
        {
            "label": "Download updated MARC",
            "data": b"updated",
            "file_name": "quick-ui_quickbatch_20260709_190000.mrc",
            "mime": "application/marc",
            "key": "quick_batch_download_updated",
        }
    ]
