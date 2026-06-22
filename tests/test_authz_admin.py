"""Admin mutations for users + allowed domains (TASK-088)."""
from __future__ import annotations

import pytest

from marcedit_web.lib import authz, db


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def test_approve_then_revoke_roundtrip():
    authz.authorize("p@gmail.com")  # creates pending
    assert [u["email"] for u in authz.list_pending()] == ["p@gmail.com"]

    authz.approve_user("p@gmail.com", by="boss@smith.edu")
    assert authz.list_pending() == []
    d = authz.authorize("p@gmail.com")
    assert d.outcome == "approved" and d.role == "cataloger"
    assert authz.get_user("p@gmail.com")["approved_by"] == "boss@smith.edu"

    authz.revoke_user("p@gmail.com", by="boss@smith.edu")
    assert authz.authorize("p@gmail.com").outcome == "revoked"


def test_set_role_to_admin():
    authz.approve_user("c@smith.edu", by="boss@smith.edu")
    authz.set_role("c@smith.edu", "admin", by="boss@smith.edu")
    assert authz.authorize("c@smith.edu").role == "admin"


def test_set_role_rejects_unknown_role():
    authz.approve_user("c@smith.edu", by="boss@smith.edu")
    with pytest.raises(ValueError):
        authz.set_role("c@smith.edu", "wizard", by="boss@smith.edu")


def test_domain_add_list_remove():
    authz.add_domain("Smith.edu", by="boss@smith.edu")
    assert authz.list_domains() == ["smith.edu"]
    authz.remove_domain("smith.edu", by="boss@smith.edu")
    assert authz.list_domains() == []
