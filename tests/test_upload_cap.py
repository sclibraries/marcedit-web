"""Public-tier upload byte cap (TASK-088)."""
from __future__ import annotations

from marcedit_web.lib import session


def test_public_default_cap_is_smaller(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "public")
    public_cap = session.max_upload_bytes()
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
    private_cap = session.max_upload_bytes()
    assert public_cap < private_cap


def test_env_override(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "1234")
    assert session.max_upload_bytes() == 1234
