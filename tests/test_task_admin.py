"""Tests for marcedit_web.lib.task_admin."""

from __future__ import annotations

import pytest

from marcedit_web.lib import task_admin


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Each test starts with the admin env var unset."""
    monkeypatch.delenv("MARCEDIT_WEB_ADMINS", raising=False)


def test_no_admins_when_env_unset():
    assert task_admin.admin_list() == []
    assert task_admin.is_admin("rconnell@smith.edu") is False
    assert task_admin.is_admin("anonymous") is False


def test_single_admin(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_ADMINS", "rconnell@smith.edu")
    assert task_admin.is_admin("rconnell@smith.edu") is True
    assert task_admin.is_admin("other@smith.edu") is False


def test_multiple_admins(monkeypatch):
    monkeypatch.setenv(
        "MARCEDIT_WEB_ADMINS",
        "rconnell@smith.edu, admin2@smith.edu , admin3@x.edu",
    )
    assert task_admin.is_admin("rconnell@smith.edu") is True
    assert task_admin.is_admin("admin2@smith.edu") is True
    assert task_admin.is_admin("admin3@x.edu") is True
    assert task_admin.is_admin("rando@smith.edu") is False


def test_wildcard_admits_everyone(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_ADMINS", "*")
    assert task_admin.is_admin("any@user.com") is True
    assert task_admin.is_admin("anonymous") is True


def test_wildcard_with_named_entries_still_open(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_ADMINS", "user@a.edu,*,user@b.edu")
    assert task_admin.is_admin("user@a.edu") is True
    assert task_admin.is_admin("user@b.edu") is True
    assert task_admin.is_admin("rando@c.edu") is True


def test_empty_user_never_admin(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_ADMINS", "*")
    assert task_admin.is_admin("") is False
    assert task_admin.is_admin(None) is False  # type: ignore[arg-type]


def test_whitespace_only_env_means_no_admins(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_ADMINS", "   ")
    assert task_admin.admin_list() == []
    assert task_admin.is_admin("anyone@x.edu") is False
