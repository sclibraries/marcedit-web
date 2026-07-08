"""Jobs page render helpers (TASK-118)."""

from __future__ import annotations

import importlib


def _load_jobs_page(monkeypatch):
    import marcedit_web.views.B_Jobs as page

    monkeypatch.setattr(page.session, "init_page", lambda: None)
    return importlib.reload(page)


def test_status_label_is_cataloger_readable(monkeypatch):
    page = _load_jobs_page(monkeypatch)

    assert page._status_label("needs_review") == "Needs review"
    assert page._status_label("ready_to_load") == "Ready to load"


def test_format_size_uses_human_units(monkeypatch):
    page = _load_jobs_page(monkeypatch)

    assert page._format_size(999) == "999 B"
    assert page._format_size(1536) == "1.5 KB"
    assert page._format_size(2 * 1024 * 1024) == "2.0 MB"
