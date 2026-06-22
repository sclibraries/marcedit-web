"""Tests for marcedit_web.lib.runmode (TASK-088)."""
from __future__ import annotations

from marcedit_web.lib import runmode


def test_default_is_private(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_MODE", raising=False)
    assert runmode.app_mode() == "private"
    assert runmode.is_private() is True
    assert runmode.is_public() is False


def test_public_mode(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "public")
    assert runmode.app_mode() == "public"
    assert runmode.is_public() is True
    assert runmode.is_private() is False


def test_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "  PUBLIC ")
    assert runmode.app_mode() == "public"


def test_unknown_value_fails_closed_to_private(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "banana")
    assert runmode.app_mode() == "private"
