# tests/test_access_gate.py
"""Private-unit access gate decision (TASK-088)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

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


def test_enforce_access_reuses_pre_resolved_decision(monkeypatch):
    decision = authz.Decision("approved", "cataloger")
    monkeypatch.setattr(access_gate.runmode, "is_public", lambda: False)
    monkeypatch.setattr(
        access_gate,
        "gate_decision",
        lambda _user: (_ for _ in ()).throw(
            AssertionError("authorization was resolved twice")
        ),
    )
    fake_streamlit = SimpleNamespace(session_state={})
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    access_gate.enforce_access(
        user="owner@smith.edu",
        decision=decision,
    )

    assert fake_streamlit.session_state["role"] == "cataloger"
