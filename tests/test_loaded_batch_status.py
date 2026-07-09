"""Tests for loaded-batch status rendering (TASK-138)."""

from __future__ import annotations

from types import SimpleNamespace


class _FakeStreamlit:
    def __init__(self):
        self.infos: list[str] = []
        self.markdowns: list[str] = []

    def info(self, message):
        self.infos.append(str(message))

    def markdown(self, message):
        self.markdowns.append(str(message))


def test_loaded_batch_status_renders_active_file(monkeypatch):
    from marcedit_web.render import batch_status

    fake_st = _FakeStreamlit()
    store = SimpleNamespace(count=lambda: 51130, malformed_count=lambda: 2)
    monkeypatch.setattr(batch_status, "st", fake_st)
    monkeypatch.setattr(batch_status.session, "current_store", lambda: store)
    monkeypatch.setattr(
        batch_status.session,
        "current_filename",
        lambda: "vendor-load.mrc",
    )

    batch_status.loaded_batch_status()

    assert fake_st.infos == []
    assert fake_st.markdowns == [
        "**Loaded batch:** `vendor-load.mrc` · 51,130 records · 2 malformed/skipped"
    ]


def test_loaded_batch_status_renders_empty_state(monkeypatch):
    from marcedit_web.render import batch_status

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(batch_status, "st", fake_st)
    monkeypatch.setattr(batch_status.session, "current_store", lambda: None)

    batch_status.loaded_batch_status()

    assert fake_st.infos == ["No MARC batch is loaded."]
    assert fake_st.markdowns == []
