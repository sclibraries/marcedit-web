"""Tests for marcedit_web.lib.quotas (per-feature byte caps)."""

from __future__ import annotations

import pytest

from marcedit_web.lib import quotas


def test_defaults_are_non_zero():
    """Sanity: every cap returns a positive byte count by default."""
    assert quotas.max_upload_bytes() > 0
    assert quotas.max_diff_bytes() > 0
    assert quotas.max_tasksfile_bytes() > 0
    assert quotas.max_session_bytes() > 0


def test_env_overrides_upload_cap(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "1024")
    assert quotas.max_upload_bytes() == 1024


def test_env_override_rejects_nonsense_and_falls_back(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "not-a-number")
    # Bad env values must not raise; the default applies.
    assert quotas.max_upload_bytes() > 0


def test_check_upload_passes_when_under_cap(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "100")
    assert quotas.check_upload(50) == 50


def test_check_upload_raises_when_over_cap(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "100")
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.check_upload(101)
    assert exc.value.kind == "upload"
    assert exc.value.attempted == 101
    assert exc.value.limit == 100


def test_check_upload_uses_kind_specific_limit(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_TASKSFILE_BYTES", "10")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "1000")
    # Same size, different kind — only the tasksfile cap rejects.
    assert quotas.check_upload(50, kind="upload") == 50
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.check_upload(50, kind="tasksfile")
    assert exc.value.kind == "tasksfile"


def test_check_upload_unknown_kind_raises_valueerror():
    with pytest.raises(ValueError):
        quotas.check_upload(1, kind="bogus")


def test_session_aggregate_tracks_running_total(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_SESSION_BYTES", "1000")
    running = 0
    running = quotas.check_session_aggregate(running, 300)
    assert running == 300
    running = quotas.check_session_aggregate(running, 600)
    assert running == 900
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.check_session_aggregate(running, 200)  # 1100 > 1000
    assert exc.value.kind == "session-aggregate"


def test_quota_exceeded_message_includes_sizes(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "5")
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.check_upload(10)
    msg = str(exc.value)
    assert "10" in msg
    assert "5" in msg
