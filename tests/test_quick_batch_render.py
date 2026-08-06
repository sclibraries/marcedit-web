"""Render-helper tests for Tasks-page quick batch operations (TASK-137)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pymarc

from marcedit_web.lib.batch_replace import BatchReplaceRequest
from marcedit_web.lib.quick_batch import QuickBatchRequest
from marcedit_web.lib.record_store import RecordStore
from marcedit_web.render import operation_activity


class _RecordingActivity:
    def __init__(self, operation_id, events=None):
        self.operation_id = operation_id
        self.phase_calls = []
        self.progress_calls = []
        self.completed = []
        self.failed = []
        self.events = events if events is not None else []
        self.progress_callback = self._progress

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def phase(self, label, message):
        self.phase_calls.append((label, message))

    def _progress(self, processed, total):
        self.progress_calls.append((processed, total))

    def complete(self, label, message):
        self.events.append("complete")
        self.completed.append((label, message))

    def fail(self, label, message):
        self.events.append("fail")
        self.failed.append((label, message))


class _RecordingActivityFactory:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.activities = []

    def __call__(self, operation_id, label, *, phase, total=None):
        activity = _RecordingActivity(operation_id, self.events)
        activity.phase_calls.append((phase, label))
        self.activities.append(activity)
        return activity


class _QuietActivity:
    progress_callback = staticmethod(lambda *_args: None)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def phase(self, *_args):
        return None

    def complete(self, *_args):
        return None

    def fail(self, *_args):
        return None


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


def _replace_request():
    return BatchReplaceRequest(
        tag="001",
        subfield=None,
        find="quick-batch-ui",
        replace="quick-ui-updated",
        regex=False,
        ignore_case=False,
    )


def _tasks_render(monkeypatch, fake_st):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    monkeypatch.setattr(
        operation_activity,
        "open_activity",
        lambda *_args, **_kwargs: _QuietActivity(),
    )
    return tasks_render


def test_quick_batch_preview_stores_non_mutating_preview(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    factory = _RecordingActivityFactory()
    monkeypatch.setattr(operation_activity, "open_activity", factory)

    request = QuickBatchRequest(kind="leader", position="05", value="c")
    tasks_render._build_and_store_quick_batch_preview(request)

    preview = fake_st.session_state[tasks_render._K_QB_PREVIEW]
    preview_store = RecordStore.from_path(preview.output_path)
    assert preview.changed_count == 1
    assert str(preview_store.get(0).leader)[5] == "c"
    assert str(store.get(0).leader)[5] == "n"
    activity = factory.activities[0]
    assert activity.operation_id == "quick-batch-preview"
    assert activity.completed
    assert activity.failed == []


def test_quick_batch_preview_passes_activity_progress_callback_at_boundaries(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    factory = _RecordingActivityFactory()
    monkeypatch.setattr(operation_activity, "open_activity", factory)
    preview = tasks_render.quick_batch.build_preview(
        store, QuickBatchRequest(kind="leader", position="05", value="c")
    )
    captured = []

    def fake_build_preview(store_arg, request_arg, *, progress):
        captured.append((request_arg, progress))
        for processed in (1, 250, 1000):
            progress(processed, 1000)
        return preview

    monkeypatch.setattr(
        tasks_render.quick_batch, "build_preview", fake_build_preview
    )
    request = QuickBatchRequest(kind="leader", position="05", value="c")

    tasks_render._build_and_store_quick_batch_preview(request)

    assert captured[0][0] is request
    assert captured[0][1] is factory.activities[0].progress_callback
    assert factory.activities[0].progress_calls == [
        (1, 1000),
        (250, 1000),
        (1000, 1000),
    ]


def test_quick_batch_apply_completes_activity_before_rerun(monkeypatch, tmp_path):
    events = []
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render.session, "current_user_id", lambda: "cataloger")
    monkeypatch.setattr(tasks_render.session, "current_filename", lambda: "quick-ui.mrc")
    monkeypatch.setattr(tasks_render, "audit_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **kwargs: {"id": 7, "job_id": kwargs["job_id"], "kind": kwargs["kind"]},
    )
    factory = _RecordingActivityFactory(events)
    monkeypatch.setattr(operation_activity, "open_activity", factory)
    original_rerun = fake_st.rerun

    def rerun():
        events.append("rerun")
        original_rerun()

    fake_st.rerun = rerun
    preview = tasks_render.quick_batch.build_preview(
        store, QuickBatchRequest(kind="leader", position="05", value="c")
    )

    tasks_render._apply_quick_batch_preview(preview)

    assert events.index("complete") < events.index("rerun")
    assert factory.activities[0].operation_id == "quick-batch-apply"


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


def test_quick_find_replace_preview_uses_activity_phases_and_preserves_request(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    request = _replace_request()
    returned_preview = tasks_render.batch_replace.build_preview(store, request)
    factory = _RecordingActivityFactory()
    monkeypatch.setattr(operation_activity, "open_activity", factory)
    captured = []

    def fake_build_preview(store_arg, request_arg):
        captured.append((store_arg, request_arg))
        return returned_preview

    monkeypatch.setattr(
        tasks_render.batch_replace, "build_preview", fake_build_preview
    )
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)

    tasks_render._build_and_store_preview(request)

    assert captured == [(store, request)]
    assert fake_st.session_state[tasks_render._K_BR_PREVIEW] is returned_preview
    activity = factory.activities[0]
    assert activity.operation_id == "quick-find-replace-preview"
    assert [label for label, _message in activity.phase_calls] == [
        "Preparing",
        "Previewing",
        "Finalizing",
    ]
    assert activity.completed


def test_quick_find_replace_apply_uses_activity_phases_and_completes_before_rerun(
    monkeypatch, tmp_path,
):
    events = []
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    request = _replace_request()
    preview = tasks_render.batch_replace.build_preview(store, request)
    factory = _RecordingActivityFactory(events)
    monkeypatch.setattr(operation_activity, "open_activity", factory)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render.session, "current_user_id", lambda: "cataloger")
    monkeypatch.setattr(tasks_render.session, "current_filename", lambda: "quick-ui.mrc")
    monkeypatch.setattr(tasks_render, "audit_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **kwargs: {"id": 7, "job_id": kwargs["job_id"], "kind": kwargs["kind"]},
    )
    original_rerun = fake_st.rerun

    def rerun():
        events.append("rerun")
        original_rerun()

    fake_st.rerun = rerun

    tasks_render._apply_quick_preview(preview)

    activity = factory.activities[0]
    assert activity.operation_id == "quick-find-replace-apply"
    assert [label for label, _message in activity.phase_calls] == [
        "Preparing",
        "Applying",
        "Finalizing",
    ]
    assert activity.completed
    assert events.index("complete") < events.index("rerun")


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


def test_render_quick_batch_export_links_job_version_history(
    monkeypatch, tmp_path,
):
    """Versioned job changes must not claim rollback history is unavailable."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    export_path = tmp_path / "quick-ui-job-export.mrc"
    export_path.write_bytes(b"updated")
    fake_st.session_state[tasks_render._K_QB_EXPORT] = {
        "filename": "quick-ui-job.mrc",
        "path": str(export_path),
        "snapshot_id": None,
        "job_file_version_id": 22,
    }

    tasks_render._render_quick_batch_export()

    assert fake_st.captions == [
        "Rollback and before/after downloads are available on the History page."
    ]


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
