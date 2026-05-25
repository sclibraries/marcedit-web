"""Tests for marcedit_web.lib.session.require_upload (Stage 22 DRY gate)."""

from __future__ import annotations

import sys
import types

import pytest

from marcedit_web.lib import session


class _FakeSt:
    """Minimal stand-in for streamlit, capturing info() / session_state."""

    def __init__(self, *, store):
        self.session_state = {"store": store}
        self.info_messages: list[str] = []

    def info(self, msg: str) -> None:
        self.info_messages.append(msg)


class _FakeStore:
    """Drop-in for RecordStore — only count() is needed by has_upload."""

    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


@pytest.fixture
def fake_st(monkeypatch):
    def _install(*, count: int | None):
        store = _FakeStore(count) if count is not None else None
        fake = _FakeSt(store=store)
        monkeypatch.setitem(sys.modules, "streamlit", fake)
        return fake

    return _install


def test_returns_true_when_upload_present(fake_st):
    fake = fake_st(count=7)
    assert session.require_upload("validate records") is True
    assert fake.info_messages == []  # no banner when satisfied


def test_returns_false_and_shows_banner_when_no_upload(fake_st):
    fake = fake_st(count=None)
    assert session.require_upload("validate records") is False
    assert len(fake.info_messages) == 1
    msg = fake.info_messages[0]
    assert "Upload a `.mrc` file on **Home**" in msg
    assert "validate records" in msg


def test_returns_false_when_store_present_but_empty(fake_st):
    """Zero-record store is treated as no upload."""
    fake = fake_st(count=0)
    assert session.require_upload("see reports") is False
    assert "see reports" in fake.info_messages[0]


def test_blurb_is_interpolated_verbatim(fake_st):
    """The blurb argument lands inside the banner without quoting."""
    fake = fake_st(count=None)
    session.require_upload("dedupe within the loaded batch")
    assert "dedupe within the loaded batch" in fake.info_messages[0]
