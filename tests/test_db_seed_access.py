"""Bootstrap seeding of admins + allowed domains (TASK-088)."""
from __future__ import annotations

from marcedit_web.lib import db


def _rows(table):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def test_seeds_admin_emails(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_ADMIN_EMAILS", "Boss@smith.edu, two@umass.edu")
    db.reset_for_tests()
    db.init_schema()
    users = {r["email"]: r for r in _rows("users")}
    assert set(users) == {"boss@smith.edu", "two@umass.edu"}
    assert all(u["role"] == "admin" and u["status"] == "approved"
               for u in users.values())
    assert users["boss@smith.edu"]["approved_by"] == "__bootstrap__"


def test_seeds_allowed_domains(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_ALLOWED_DOMAINS", "smith.edu, UMASS.edu")
    db.reset_for_tests()
    db.init_schema()
    domains = {r["domain"] for r in _rows("allowed_domains")}
    assert domains == {"smith.edu", "umass.edu"}


def test_seed_is_idempotent_and_promotion_only(monkeypatch):
    # First boot: user exists as a plain cataloger.
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at)"
            " VALUES (?, ?, ?, ?)",
            ("x@smith.edu", "cataloger", "approved", "2026-06-22T00:00:00Z"),
        )
    # Re-boot with x as a bootstrap admin.
    monkeypatch.setenv("MARCEDIT_WEB_ADMIN_EMAILS", "x@smith.edu")
    db.reset_for_tests()
    db.init_schema()
    db.reset_for_tests()
    db.init_schema()  # twice — must not duplicate
    rows = [r for r in _rows("users") if r["email"] == "x@smith.edu"]
    assert len(rows) == 1
    assert rows[0]["role"] == "admin" and rows[0]["status"] == "approved"


def test_no_env_seeds_nothing(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("MARCEDIT_WEB_ALLOWED_DOMAINS", raising=False)
    db.reset_for_tests()
    db.init_schema()
    assert _rows("users") == []
    assert _rows("allowed_domains") == []


def test_demotion_omission_is_noop(monkeypatch):
    """Seeding only touches emails in env; omitting an admin is a no-op."""
    # First boot: seed an admin via env.
    monkeypatch.setenv("MARCEDIT_WEB_ADMIN_EMAILS", "admin@smith.edu")
    db.reset_for_tests()
    db.init_schema()
    users = {r["email"]: r for r in _rows("users")}
    assert users["admin@smith.edu"]["role"] == "admin"
    assert users["admin@smith.edu"]["status"] == "approved"

    # Re-boot with that email OMITTED from env.
    monkeypatch.setenv("MARCEDIT_WEB_ADMIN_EMAILS", "")
    db.reset_for_tests()
    db.init_schema()
    users = {r["email"]: r for r in _rows("users")}
    # Admin unchanged — still admin and approved.
    assert users["admin@smith.edu"]["role"] == "admin"
    assert users["admin@smith.edu"]["status"] == "approved"


def test_approver_preserved_on_promotion(monkeypatch):
    """Promoting a user preserves their human approver; new bootstrap admins get __bootstrap__."""
    # Insert a user pre-approved by a real admin.
    db.reset_for_tests()
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at, approved_at, approved_by)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("user@smith.edu", "cataloger", "approved",
             "2026-06-22T00:00:00Z", "2026-06-22T00:00:00Z", "admin@smith.edu"),
        )

    # Seed with that user in admin emails; should promote but preserve approver.
    monkeypatch.setenv("MARCEDIT_WEB_ADMIN_EMAILS", "user@smith.edu, newadmin@smith.edu")
    db.reset_for_tests()
    db.init_schema()
    users = {r["email"]: r for r in _rows("users")}

    # Existing user: promoted to admin, approver preserved.
    assert users["user@smith.edu"]["role"] == "admin"
    assert users["user@smith.edu"]["status"] == "approved"
    assert users["user@smith.edu"]["approved_by"] == "admin@smith.edu"

    # New bootstrap user: gets __bootstrap__.
    assert users["newadmin@smith.edu"]["role"] == "admin"
    assert users["newadmin@smith.edu"]["status"] == "approved"
    assert users["newadmin@smith.edu"]["approved_by"] == "__bootstrap__"
