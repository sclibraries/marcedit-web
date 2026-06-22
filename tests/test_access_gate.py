# tests/test_access_gate.py
"""Private-unit access gate decision (TASK-088)."""
from __future__ import annotations

import pytest

from marcedit_web.lib import access_gate, authz, db


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def test_gate_denies_anonymous(monkeypatch):
    monkeypatch.setattr(access_gate, "_resolve_user", lambda: "anonymous")
    assert access_gate.gate_decision().outcome == "denied"


def test_gate_approves_allowlisted(monkeypatch):
    authz.add_domain("smith.edu", by="test")
    monkeypatch.setattr(access_gate, "_resolve_user", lambda: "new@smith.edu")
    d = access_gate.gate_decision()
    assert d.outcome == "approved" and d.role == "cataloger"


def test_gate_pending_for_unlisted(monkeypatch):
    monkeypatch.setattr(access_gate, "_resolve_user", lambda: "x@gmail.com")
    assert access_gate.gate_decision().outcome == "pending"
