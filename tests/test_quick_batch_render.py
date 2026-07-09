"""Render-helper tests for Tasks-page quick batch operations (TASK-137)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pymarc

from marcedit_web.lib.quick_batch import QuickBatchRequest
from marcedit_web.lib.record_store import RecordStore


class _Spinner:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.spinners: list[str] = []
        self.rerun_called = False

    def error(self, message):
        self.errors.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def spinner(self, message):
        self.spinners.append(str(message))
        return _Spinner()

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


def test_quick_batch_apply_mutates_store_clears_cache_and_audits(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    fake_st.session_state["issues_cache"] = {"stale": object()}
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    events: list[dict] = []

    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render.session, "current_user_id", lambda: "cataloger")
    monkeypatch.setattr(tasks_render.session, "current_filename", lambda: "quick-ui.mrc")
    monkeypatch.setattr(
        tasks_render,
        "audit_event",
        lambda event, **payload: events.append({"event": event, **payload}),
    )

    request = QuickBatchRequest(kind="leader", position="05", value="c")
    preview = tasks_render.quick_batch.build_preview(store, request)
    fake_st.session_state[tasks_render._K_QB_PREVIEW] = preview

    tasks_render._apply_quick_batch_preview(preview)

    assert str(store.get(0).leader)[5] == "c"
    assert fake_st.session_state["issues_cache"] == {}
    assert tasks_render._K_QB_PREVIEW not in fake_st.session_state
    assert events == [
        {
            "event": "quick-batch-applied",
            "user": "cataloger",
            "filename": "quick-ui.mrc",
            "kind": "leader",
            "changed_count": 1,
            "skipped_count": 0,
        }
    ]
    assert fake_st.successes == ["Applied quick batch operation to 1 record(s)."]
    assert fake_st.spinners == [
        "Applying quick batch operation to 1 record…"
    ]
    assert fake_st.rerun_called is True
