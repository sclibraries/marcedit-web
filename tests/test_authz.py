# tests/test_authz.py
"""Tests for the authorization decision layer (TASK-088)."""
from __future__ import annotations

import pytest

from marcedit_web.lib import authz, db


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def _add_domain(domain):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO allowed_domains(domain, added_at, added_by)"
            " VALUES (?, '2026-06-22T00:00:00Z', 'test')",
            (domain,),
        )


def test_domain_of():
    assert authz.domain_of("Alice@Smith.EDU") == "smith.edu"
    assert authz.domain_of("nodomain") == ""


def test_anonymous_is_denied():
    d = authz.authorize("anonymous")
    assert d.outcome == "denied" and d.role is None


def test_allowlisted_domain_auto_approves_as_cataloger():
    _add_domain("smith.edu")
    d = authz.authorize("new@smith.edu")
    assert d.outcome == "approved" and d.role == "cataloger"
    row = authz.get_user("new@smith.edu")
    assert row["status"] == "approved" and row["approved_by"] == "__domain__"


def test_unlisted_domain_goes_pending():
    d = authz.authorize("stranger@gmail.com")
    assert d.outcome == "pending" and d.role is None
    assert authz.get_user("stranger@gmail.com")["status"] == "pending"


def test_pending_is_idempotent_no_duplicate():
    authz.authorize("stranger@gmail.com")
    authz.authorize("stranger@gmail.com")
    with db.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE email=?",
            ("stranger@gmail.com",),
        ).fetchone()["n"]
    assert n == 1


def test_existing_row_wins_over_domain_allowlist():
    # A revoked user on an allowlisted domain stays revoked.
    _add_domain("smith.edu")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at)"
            " VALUES ('bad@smith.edu', 'cataloger', 'revoked', '2026-01-01T00:00:00Z')",
        )
    d = authz.authorize("bad@smith.edu")
    assert d.outcome == "revoked"
    assert d.role is None


def test_approved_admin_returns_admin_role():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at)"
            " VALUES ('boss@smith.edu', 'admin', 'approved', '2026-01-01T00:00:00Z')",
        )
    d = authz.authorize("boss@smith.edu")
    assert d.outcome == "approved" and d.role == "admin"
