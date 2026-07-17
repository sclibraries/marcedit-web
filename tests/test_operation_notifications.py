"""Persistent, source-safe operation notifications (TASK-156)."""

from __future__ import annotations

import importlib
import inspect
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from marcedit_web.lib import db, operations


def _insert_operation(
    operation_id: int,
    *,
    submitted_by: str = "Owner@Smith.edu",
    state: str = "completed",
    error_count: int = 0,
    cancelled_by: str | None = None,
    completed_at: str = "2026-07-17T12:00:00Z",
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO operations(id,kind,request_version,submitted_by,state,"
            "phase,request_json,total_records,error_count,submitted_at,"
            "completed_at,cancel_requested_by) VALUES "
            "(?,'saved-task-run',1,?,?,?,?,?,?,?, ?,?)",
            (
                operation_id,
                submitted_by,
                state,
                state,
                '{"version":1,"tasks":[{"name":"secret task"}]}',
                10,
                error_count,
                "2026-07-17T11:00:00Z",
                completed_at,
                cancelled_by,
            ),
        )


def test_unread_notifications_are_terminal_submitter_owned_and_source_safe():
    db.init_schema()
    _insert_operation(1)
    _insert_operation(2, state="failed")
    _insert_operation(3, state="cancelled", cancelled_by="admin@smith.edu")
    _insert_operation(4, state="cancelled", cancelled_by=" OWNER@smith.edu ")
    _insert_operation(5, state="running", completed_at=None)
    _insert_operation(6, submitted_by="other@smith.edu")

    rows = operations.list_unread_notifications(" OWNER@smith.edu ")

    assert [row["id"] for row in rows] == [3, 2, 1]
    assert set(rows[0]) == {
        "id", "state", "error_count", "completed_at", "cancel_requested_by",
    }
    rendered = repr(rows)
    assert "secret task" not in rendered
    assert "file_path" not in rendered


def test_acknowledgement_one_and_all_are_authorized_and_idempotent():
    db.init_schema()
    _insert_operation(1)
    _insert_operation(2, state="failed")
    _insert_operation(3, submitted_by="other@smith.edu")

    first = operations.acknowledge_notification(1, by="owner@smith.edu")
    second = operations.acknowledge_notification(1, by="owner@smith.edu")
    assert first["notification_ack_at"] == second["notification_ack_at"]
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM operation_events"
            " WHERE operation_id=1 AND kind='acknowledged'"
        ).fetchone()[0] == 1

    assert operations.acknowledge_all_notifications(
        by=" OWNER@smith.edu "
    ) == 1
    assert operations.list_unread_notifications("owner@smith.edu") == []
    assert [row["id"] for row in operations.list_unread_notifications(
        "other@smith.edu"
    )] == [3]


def test_concurrent_notification_acknowledgement_records_one_event():
    db.init_schema()
    _insert_operation(1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(
            lambda _index: operations.acknowledge_notification(
                1, by="owner@smith.edu"
            ),
            range(2),
        ))

    assert rows[0]["notification_ack_at"] == rows[1]["notification_ack_at"]
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM operation_events"
            " WHERE operation_id=1 AND kind='acknowledged'"
        ).fetchone()[0] == 1


def test_status_counts_are_private_to_quick_load_submitter_and_admin():
    db.init_schema()
    _insert_operation(1, state="queued", completed_at=None)
    _insert_operation(
        2,
        submitted_by="other@smith.edu",
        state="failed",
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email,role,status,created_at)"
            " VALUES('admin@smith.edu','admin','approved','2026-07-17T10:00:00Z')"
        )

    assert operations.operation_status_counts("owner@smith.edu") == {
        "queued": 1, "running": 0, "attention": 0,
    }
    assert operations.operation_status_counts("other@smith.edu") == {
        "queued": 0, "running": 0, "attention": 1,
    }
    assert operations.operation_status_counts("admin@smith.edu") == {
        "queued": 1, "running": 0, "attention": 1,
    }


class _FakeStreamlit:
    def __init__(self, clicked=()):
        self.session_state = {}
        self.clicked = set(clicked)
        self.popovers = []
        self.buttons = []
        self.page_links = []
        self.successes = []
        self.warnings = []
        self.errors = []
        self.captions = []
        self.markdowns = []
        self.rerun_called = False
        self.sidebar = nullcontext()

    def popover(self, label, **kwargs):
        self.popovers.append({"label": label, **kwargs})
        return nullcontext()

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return kwargs.get("key") in self.clicked

    def page_link(self, page, **kwargs):
        self.page_links.append({"page": page, **kwargs})

    def success(self, value):
        self.successes.append(str(value))

    def warning(self, value):
        self.warnings.append(str(value))

    def error(self, value):
        self.errors.append(str(value))

    def caption(self, value):
        self.captions.append(str(value))

    def markdown(self, value, **_kwargs):
        self.markdowns.append(str(value))

    def rerun(self):
        self.rerun_called = True


def _notification_renderer(monkeypatch, fake_st):
    from marcedit_web.render import operation_notifications

    monkeypatch.setattr(operation_notifications, "st", fake_st)
    return operation_notifications


def test_header_bell_uses_material_icon_and_generic_source_safe_copy(monkeypatch):
    fake_st = _FakeStreamlit()
    renderer = _notification_renderer(monkeypatch, fake_st)
    monkeypatch.setattr(
        renderer.operations,
        "list_unread_notifications",
        lambda _user: [{
            "id": 42,
            "state": "completed",
            "error_count": 0,
            "completed_at": "2026-07-17T12:00:00Z",
            "cancel_requested_by": None,
        }],
    )

    renderer.render_header_bell("owner@smith.edu")

    assert fake_st.popovers == [{
        "label": "Notifications (1)",
        "icon": ":material/notifications:",
    }]
    assert fake_st.page_links == [{
        "page": "views/D_Operations.py",
        "label": "View operation 42",
        "icon": ":material/open_in_new:",
    }]
    rendered = " ".join(
        fake_st.successes + fake_st.warnings + fake_st.errors + fake_st.captions
    )
    assert "Operation 42 completed" in rendered
    assert "secret" not in rendered
    assert "🔔" not in rendered


def test_bell_mark_one_and_all_use_unique_keys(monkeypatch):
    fake_st = _FakeStreamlit(clicked={"operation_notification_read_8"})
    renderer = _notification_renderer(monkeypatch, fake_st)
    notifications = [
        {"id": operation_id, "state": "failed", "error_count": 0,
         "completed_at": "2026-07-17T12:00:00Z", "cancel_requested_by": None}
        for operation_id in (8, 7)
    ]
    monkeypatch.setattr(
        renderer.operations, "list_unread_notifications", lambda _user: notifications
    )
    acknowledged = []
    monkeypatch.setattr(
        renderer.operations,
        "acknowledge_notification",
        lambda operation_id, *, by: acknowledged.append((operation_id, by)),
    )
    monkeypatch.setattr(
        renderer.operations,
        "acknowledge_all_notifications",
        lambda *, by: acknowledged.append(("all", by)),
    )

    renderer.render_header_bell("owner@smith.edu")

    assert acknowledged == [(8, "owner@smith.edu")]
    keys = [button["key"] for button in fake_st.buttons]
    assert keys == [
        "operation_notification_read_8",
        "operation_notification_read_7",
        "operation_notifications_read_all",
    ]
    assert fake_st.rerun_called is True


def test_first_return_notice_shows_each_newest_unread_once_per_session(monkeypatch):
    fake_st = _FakeStreamlit()
    renderer = _notification_renderer(monkeypatch, fake_st)
    rows = [
        {"id": 11, "state": "failed", "error_count": 0,
         "completed_at": "2026-07-17T12:00:00Z", "cancel_requested_by": None},
        {"id": 10, "state": "completed", "error_count": 3,
         "completed_at": "2026-07-17T11:00:00Z", "cancel_requested_by": None},
        {"id": 9, "state": "cancelled", "error_count": 0,
         "completed_at": "2026-07-17T10:00:00Z",
         "cancel_requested_by": "admin@smith.edu"},
    ]
    monkeypatch.setattr(
        renderer.operations, "list_unread_notifications", lambda _user: rows
    )

    renderer.render_first_return_notice("owner@smith.edu")
    renderer.render_first_return_notice("owner@smith.edu")
    rows.insert(0, {
        "id": 12, "state": "completed", "error_count": 3,
        "completed_at": "2026-07-17T13:00:00Z", "cancel_requested_by": None,
    })
    renderer.render_first_return_notice("owner@smith.edu")

    assert fake_st.errors == [
        "Operation 11 failed. Open Operations to review the error details."
    ]
    assert fake_st.warnings == [
        "Operation 12 completed with 3 record errors. Open Operations to review.",
    ]
    assert len(fake_st.page_links) == 2


def test_cancelled_by_other_first_return_uses_warning(monkeypatch):
    fake_st = _FakeStreamlit()
    renderer = _notification_renderer(monkeypatch, fake_st)
    monkeypatch.setattr(
        renderer.operations,
        "list_unread_notifications",
        lambda _user: [{
            "id": 9, "state": "cancelled", "error_count": 0,
            "completed_at": "2026-07-17T10:00:00Z",
            "cancel_requested_by": "admin@smith.edu",
        }],
    )

    renderer.render_first_return_notice("owner@smith.edu")

    assert fake_st.warnings == [
        "Operation 9 was cancelled by another user. Open Operations to review."
    ]


def test_sidebar_summary_uses_compact_counts_and_operations_link(monkeypatch):
    fake_st = _FakeStreamlit()
    renderer = _notification_renderer(monkeypatch, fake_st)
    monkeypatch.setattr(
        renderer.operations,
        "operation_status_counts",
        lambda _user: {"queued": 2, "running": 1, "attention": 3},
    )

    renderer.render_sidebar_summary("owner@smith.edu")

    assert fake_st.captions == ["Operations: 2 queued · 1 running · 3 attention"]
    assert fake_st.page_links == [{
        "page": "views/D_Operations.py",
        "label": "Open Operations",
        "icon": ":material/pending_actions:",
    }]


def test_public_mode_guards_header_return_notice_and_sidebar_without_db(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    renderer = _notification_renderer(monkeypatch, fake_st)
    monkeypatch.setattr(renderer.runmode, "is_private", lambda: False)
    monkeypatch.setattr(
        renderer.operations,
        "list_unread_notifications",
        lambda _user: (_ for _ in ()).throw(AssertionError("database opened")),
    )
    monkeypatch.setattr(
        renderer.operations,
        "operation_status_counts",
        lambda _user: (_ for _ in ()).throw(AssertionError("database opened")),
    )

    renderer.render_header_bell("anonymous")
    renderer.render_first_return_notice("anonymous")
    renderer.render_sidebar_summary("anonymous")

    assert fake_st.popovers == []
    assert fake_st.page_links == []


def test_app_header_only_adds_bell_for_private_approved_users(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
    import marcedit_web.App as app

    app = importlib.reload(app)
    calls = []
    monkeypatch.setattr(
        app.operation_notifications,
        "render_header_bell",
        lambda email: calls.append(email),
    )
    monkeypatch.setattr(
        app.authz, "get_user", lambda _email: {"status": "approved"}
    )

    assert app._should_render_notification_bell("owner@smith.edu") is True
    app._render_notification_bell("owner@smith.edu")
    assert calls == ["owner@smith.edu"]

    monkeypatch.setattr(app.authz, "get_user", lambda _email: {"status": "pending"})
    assert app._should_render_notification_bell("owner@smith.edu") is False
    monkeypatch.setattr(app.runmode, "is_private", lambda: False)
    assert app._should_render_notification_bell("owner@smith.edu") is False


def test_app_calls_first_return_only_after_access_gate_and_before_navigation():
    import marcedit_web.App as app

    source = inspect.getsource(app)
    gate = source.index("access_gate.enforce_access()")
    notice = source.index("_render_first_return_notification()", gate)
    navigation = source.index("st.navigation(", notice)
    assert gate < notice < navigation
