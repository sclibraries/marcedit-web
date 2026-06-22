"""Regression test: public tier must never create or touch the catalog DB.

TASK-088 final-review fix — the spec (§1) claims the public process touches
no catalog DB "by construction". This test proves that claim holds in code,
not just because the prod filesystem is read-only.
"""

from __future__ import annotations

from marcedit_web.lib import audit, db


def test_public_mode_audit_does_not_create_db(tmp_path, monkeypatch):
    """audit_event in public mode must not create the catalog DB file."""
    db_path = tmp_path / "should-not-be-created.db"
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "public")
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(db_path))
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path / "audit"))
    db.reset_for_tests()

    audit.audit_event("upload-accepted", user="anonymous")

    assert not db_path.exists(), (
        "public-mode audit_event must not create the catalog DB"
    )


def test_private_mode_audit_does_create_db(tmp_path, monkeypatch):
    """Contrasting assertion: private mode DOES write to the DB."""
    db_path = tmp_path / "should-be-created.db"
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(db_path))
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path / "audit"))
    db.reset_for_tests()

    audit.audit_event("upload-accepted", user="alice@example.edu")

    assert db_path.exists(), (
        "private-mode audit_event must write to the catalog DB"
    )
