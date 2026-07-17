"""Mode-driven page registration (TASK-088) — the load-bearing
'public tier has no sandbox' assertion."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from marcedit_web.lib import db, identity


APP_PATH = Path(__file__).parent.parent / "marcedit_web" / "App.py"

PUBLIC_ALLOWED = {"Home", "View", "Validate", "Report", "MarcTools"}
PRIVATE_ONLY = {
    "Workspace", "Jobs", "History", "Operations", "Find", "MarcEditor",
    "Tasks", "Diff", "Dedupe", "Admin",
}
SANDBOX = "Tasks"
ADMIN = "Admin"


def _url_paths(pages):
    return {p.url_path for group in pages.values() for p in group}


def _load_app(monkeypatch, mode):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", mode)
    import marcedit_web.App as app
    return importlib.reload(app)


def test_public_mode_registers_only_light_pages(monkeypatch):
    app = _load_app(monkeypatch, "public")
    paths = _url_paths(app.build_pages(public=True))
    assert paths == PUBLIC_ALLOWED
    assert SANDBOX not in paths
    assert ADMIN not in paths


def test_private_mode_includes_sandbox(monkeypatch):
    app = _load_app(monkeypatch, "private")
    paths = _url_paths(app.build_pages(public=False))
    assert SANDBOX in paths
    assert PUBLIC_ALLOWED.issubset(paths)
    assert ADMIN in paths
    assert PRIVATE_ONLY.issubset(paths)


def test_private_mode_includes_jobs_page(monkeypatch):
    app = _load_app(monkeypatch, "private")
    paths = _url_paths(app.build_pages(public=False))
    assert "Jobs" in paths


def test_public_mode_does_not_register_jobs_page(monkeypatch):
    app = _load_app(monkeypatch, "public")
    paths = _url_paths(app.build_pages(public=True))
    assert "Jobs" not in paths


def test_private_mode_registers_operations_with_material_icon(monkeypatch):
    app = _load_app(monkeypatch, "private")
    pages = app.build_pages(public=False)
    operation_page = next(
        page for page in pages["Start"] if page.url_path == "Operations"
    )
    assert operation_page.script == "views/D_Operations.py"
    assert operation_page.icon == ":material/pending_actions:"


def test_public_mode_never_registers_operations(monkeypatch):
    app = _load_app(monkeypatch, "public")
    assert "Operations" not in _url_paths(app.build_pages(public=True))


def _insert_approved_user_with_notifications(email: str, count: int = 2) -> None:
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email,role,status,created_at)"
            " VALUES(?,'cataloger','approved','2026-07-17T12:00:00Z')",
            (email,),
        )
        for operation_id in range(1, count + 1):
            conn.execute(
                "INSERT INTO operations(id,kind,submitted_by,state,phase,"
                "request_json,total_records,error_count,submitted_at,completed_at)"
                " VALUES(?,'saved-task-run',?,'completed','completed','{}',1,0,"
                "'2026-07-17T12:00:00Z',?)",
                (operation_id, email, f"2026-07-17T12:0{operation_id}:00Z"),
            )


def _private_app_test(monkeypatch, email: str) -> AppTest:
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
    monkeypatch.setattr(identity, "is_oauth_configured", lambda: True)
    monkeypatch.setattr(identity, "oauth_user", lambda: email)
    monkeypatch.setattr(identity, "current_user", lambda: email)
    app_test = AppTest.from_file(APP_PATH, default_timeout=10)
    app_test.session_state["user"] = email
    return app_test


def _insert_user(email: str, status: str) -> None:
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email,role,status,created_at)"
            " VALUES(?,'cataloger',?,'2026-07-17T12:00:00Z')",
            (email, status),
        )


def test_real_streamlit_registers_operations_before_notification_links(
    monkeypatch,
):
    email = "owner@smith.edu"
    _insert_approved_user_with_notifications(email)

    app_test = _private_app_test(monkeypatch, email).run()

    assert list(app_test.exception) == []
    assert [block.proto.popover.label for block in app_test.get("popover")] == [
        "Notifications (2)",
        "Account",
    ]
    assert [element.proto.label for element in app_test.get("page_link")] == [
        "View operation 2",
        "View operation 1",
        "View operation 2",
    ]
    assert [button.label for button in app_test.button] == [
        "Mark read",
        "Mark read",
        "Mark all read",
        "Sign out",
    ]

    app_test = next(
        button for button in app_test.button if button.label == "Mark read"
    ).click().run()
    with db.connect() as conn:
        acknowledged = conn.execute(
            "SELECT COUNT(*) FROM operations"
            " WHERE notification_ack_at IS NOT NULL"
        ).fetchone()[0]
    assert acknowledged == 1

    app_test = next(
        button for button in app_test.button if button.label == "Mark all read"
    ).click().run()
    with db.connect() as conn:
        acknowledged = conn.execute(
            "SELECT COUNT(*) FROM operations"
            " WHERE notification_ack_at IS NOT NULL"
        ).fetchone()[0]
    assert acknowledged == 2


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("pending", "awaiting approval"),
        ("revoked", "Access revoked"),
    ],
)
def test_real_streamlit_does_not_register_private_pages_for_blocked_user(
    monkeypatch, status, message,
):
    email = f"{status}@example.com"
    _insert_user(email, status)

    app_test = _private_app_test(monkeypatch, email).run()

    assert list(app_test.exception) == []
    assert message in app_test.error[0].value
    assert list(app_test.get("page_link")) == []
    assert "Operations" not in str(app_test.sidebar)


def test_real_streamlit_does_not_register_private_pages_when_signed_out(
    monkeypatch,
):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
    monkeypatch.setattr(identity, "is_oauth_configured", lambda: True)
    monkeypatch.setattr(identity, "oauth_user", lambda: None)
    monkeypatch.setattr(identity, "current_user", lambda: "anonymous")

    app_test = AppTest.from_file(APP_PATH, default_timeout=10).run()

    assert list(app_test.exception) == []
    assert "Sign-in required" in app_test.error[0].value
    assert list(app_test.get("page_link")) == []
    assert "Operations" not in str(app_test.sidebar)
