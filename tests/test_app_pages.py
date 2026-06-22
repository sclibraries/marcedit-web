"""Mode-driven page registration (TASK-088) — the load-bearing
'public tier has no sandbox' assertion."""
from __future__ import annotations

import importlib

PUBLIC_ALLOWED = {"Home", "View", "Validate", "Report", "MarcTools"}
SANDBOX = "Tasks"
ADMIN = "Admin"


def _url_paths(pages):
    return {p.url_path for group in pages.values() for p in group}


def _load_app(monkeypatch, mode):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", mode)
    import marcedit_web.App as app
    return importlib.reload(app)


def test_public_mode_registers_only_light_pages(monkeypatch):
    app = _load_app(monkeypatch, "public")
    paths = _url_paths(app.build_pages(public=True))
    assert paths == PUBLIC_ALLOWED
    assert SANDBOX not in paths
    assert ADMIN not in paths


def test_private_mode_includes_sandbox(monkeypatch):
    app = _load_app(monkeypatch, "private")
    paths = _url_paths(app.build_pages(public=False))
    assert SANDBOX in paths
    assert PUBLIC_ALLOWED.issubset(paths)
    assert ADMIN in paths
