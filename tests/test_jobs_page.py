"""Jobs page render helpers (TASK-118)."""

from __future__ import annotations

import importlib
import sys
from typing import Any


class _FakeContainer:
    def __init__(self, st: "_FakeStreamlit" | None = None) -> None:
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write(self, value: Any) -> None:
        if self._st is not None:
            self._st.writes.append(value)

    def caption(self, text: str) -> None:
        if self._st is not None:
            self._st.captions.append(text)


class _FakeColumn:
    def __init__(self, st: "_FakeStreamlit") -> None:
        self._st = st

    def subheader(self, text: str) -> None:
        self._st.subheaders.append(text)

    def write(self, value: Any) -> None:
        self._st.writes.append(value)

    def markdown(self, text: str) -> None:
        self._st.writes.append(text)

    def button(self, label: str, **kwargs: Any) -> bool:
        self._st.button_calls.append((label, kwargs))
        return kwargs.get("key") in self._st.clicked_keys

    def popover(self, label: str, **kwargs: Any) -> _FakeContainer:
        self._st.popovers.append(label)
        return _FakeContainer(self._st)


class _FakeStreamlit:
    def __init__(
        self,
        *,
        session_state: dict[str, Any] | None = None,
        toggle_value: bool = False,
        clicked_keys: set[str] | None = None,
    ) -> None:
        self.session_state = session_state or {}
        self.toggle_value = toggle_value
        self.clicked_keys = clicked_keys or set()
        self.titles: list[str] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.subheaders: list[str] = []
        self.writes: list[Any] = []
        self.dataframes: list[tuple[Any, dict[str, Any]]] = []
        self.button_calls: list[tuple[str, dict[str, Any]]] = []
        self.toggle_calls: list[tuple[str, dict[str, Any]]] = []
        self.selectbox_calls: list[tuple[str, Any, dict[str, Any]]] = []
        self.text_input_calls: list[tuple[str, dict[str, Any]]] = []
        self.text_area_calls: list[tuple[str, dict[str, Any]]] = []
        self.popovers: list[str] = []
        self.column_calls: list[tuple[Any, dict[str, Any]]] = []
        self.dialogs: list[str] = []
        self.toasts: list[tuple[str, Any]] = []
        self.warnings: list[str] = []
        self.file_uploader_labels: list[str] = []
        self.rerun_called = False

    def title(self, text: str) -> None:
        self.titles.append(text)

    def warning(self, text: str) -> None:
        self.warnings.append(text)

    def toast(self, message: str, icon: Any = None) -> None:
        self.toasts.append((message, icon))

    def dialog(self, title: str, **kwargs: Any):
        # Passthrough decorator: the dialog body renders inline so
        # clicked_keys can drive its buttons.
        self.dialogs.append(title)

        def _decorator(func):
            return func

        return _decorator

    def caption(self, text: str) -> None:
        self.captions.append(text)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)

    def success(self, text: str) -> None:
        self.successes.append(text)

    def toggle(self, label: str, **kwargs: Any) -> bool:
        self.toggle_calls.append((label, kwargs))
        return self.toggle_value

    def container(self, **kwargs: Any) -> _FakeContainer:
        return _FakeContainer(self)

    def columns(self, spec: list[Any], **kwargs: Any) -> list[_FakeColumn]:
        self.column_calls.append((spec, kwargs))
        return [_FakeColumn(self) for _ in spec]

    def divider(self) -> None:
        return None

    def markdown(self, text: str) -> None:
        self.writes.append(text)

    def button(self, label: str, **kwargs: Any) -> bool:
        self.button_calls.append((label, kwargs))
        return kwargs.get("key") in self.clicked_keys

    def rerun(self) -> None:
        self.rerun_called = True

    def subheader(self, text: str) -> None:
        self.subheaders.append(text)

    def dataframe(self, data: Any, **kwargs: Any) -> None:
        self.dataframes.append((data, kwargs))

    def write(self, value: Any) -> None:
        self.writes.append(value)

    def selectbox(self, label: str, options: Any, **kwargs: Any) -> Any:
        self.selectbox_calls.append((label, options, kwargs))
        if "index" in kwargs:
            return options[kwargs["index"]]
        return options[0]

    def text_input(self, label: str, **kwargs: Any) -> str:
        self.text_input_calls.append((label, kwargs))
        return ""

    def text_area(self, label: str, **kwargs: Any) -> str:
        self.text_area_calls.append((label, kwargs))
        return ""

    def file_uploader(self, label: str, **kwargs: Any) -> None:
        self.file_uploader_labels.append(label)
        return None

    def switch_page(self, path: str) -> None:
        self.session_state["switched_to"] = path


def _load_jobs_page(monkeypatch):
    import marcedit_web.views.B_Jobs as page

    monkeypatch.setattr(page.session, "init_page", lambda: None)
    return importlib.reload(page)


def _job_file_row(file_id: int = 99) -> dict[str, Any]:
    return {
        "id": file_id,
        "display_name": "batch.mrc",
        "status": "new",
        "current_version_id": 123,
        "current_version_number": 1,
        "current_record_count": 42,
        "updated_by": "alice@example.edu",
        "updated_at": "2026-07-08T12:00:00Z",
    }


def test_status_label_is_cataloger_readable(monkeypatch):
    page = _load_jobs_page(monkeypatch)

    assert page._status_label("needs_review") == "Needs review"
    assert page._status_label("ready_to_load") == "Ready to load"


def test_format_size_uses_human_units(monkeypatch):
    from marcedit_web.render.job_files import format_size

    assert format_size(999) == "999 B"
    assert format_size(1536) == "1.5 KB"
    assert format_size(2 * 1024 * 1024) == "2.0 MB"


def test_job_page_permissions_are_role_based(monkeypatch):
    page = _load_jobs_page(monkeypatch)

    assert page._can_edit("owner") is True
    assert page._can_edit("editor") is True
    assert page._can_edit("viewer") is False
    assert page._can_manage("owner") is True
    assert page._can_manage("editor") is False


def test_render_list_calls_list_job_summaries_for_authenticated_user(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.session, "current_user_id", lambda: "alice@example.edu")
    monkeypatch.setattr(
        page.jobs,
        "list_job_summaries",
        lambda user_email, *, include_archived=False: calls.append((user_email, include_archived)) or [],
    )

    page._render()

    assert calls == [("alice@example.edu", False)]
    assert fake_st.infos == ["No jobs found."]


def test_render_detail_calls_uploads_and_activity_for_selected_job(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit(session_state={"selected_job_detail_id": "17"})
    upload_calls: list[int] = []
    activity_calls: list[tuple[int, str]] = []

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.session, "current_user_id", lambda: "alice@example.edu")
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "editor")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "needs_review",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(
        page.work_files,
        "list_files",
        lambda job_id, user: upload_calls.append(job_id) or [_job_file_row()],
    )
    monkeypatch.setattr(
        page.jobs,
        "list_activity",
        lambda job_id, *, user_email: activity_calls.append((job_id, user_email)) or [{
            "created_at": "2026-07-08T12:01:00Z",
            "actor_email": "owner@example.edu",
            "message": "Uploaded batch.mrc",
        }],
    )
    monkeypatch.setattr(
        page.jobs,
        "list_access",
        lambda job_id: [{
            "job_id": job_id,
            "user_email": "owner@example.edu",
            "role": "owner",
            "created_at": "2026-07-08T12:00:00Z",
        }],
    )
    monkeypatch.setattr(
        page.jobs,
        "list_review_notes",
        lambda job_id, *, user_email, include_resolved=True: [],
    )

    page._render()

    assert upload_calls == [17]
    assert activity_calls == [(17, "alice@example.edu")]
    assert fake_st.titles == ["Vendor load"]
    # Files render as the shared actionable table now (TASK-129); the only
    # remaining dataframe is the Activity feed.
    assert len(fake_st.dataframes) == 1
    assert "**Name**" in fake_st.writes
    assert "**Version**" in fake_st.writes
    assert "v1" in fake_st.writes


def test_jobs_detail_renders_attach_control_for_editor(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda *_args: "editor")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Routledge",
            "status": "active",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(page.jobs, "list_job_uploads", lambda _job_id: [])
    monkeypatch.setattr(page.jobs, "list_access", lambda _job_id: [])
    monkeypatch.setattr(page.jobs, "list_review_notes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(page.jobs, "list_activity", lambda *_args, **_kwargs: [])

    page._render_detail("editor@example.edu", 17)

    assert "Attach MARC file" in fake_st.file_uploader_labels


def test_viewer_does_not_get_attach_control(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda *_args: "viewer")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Routledge",
            "status": "active",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(page.jobs, "list_job_uploads", lambda _job_id: [])
    monkeypatch.setattr(page.jobs, "list_access", lambda _job_id: [])
    monkeypatch.setattr(page.jobs, "list_review_notes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(page.jobs, "list_activity", lambda *_args, **_kwargs: [])

    page._render_detail("viewer@example.edu", 17)

    assert "Attach MARC file" not in fake_st.file_uploader_labels


def test_render_detail_hides_archive_until_editor_holds_checkout(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.session, "current_user_id", lambda: "alice@example.edu")
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "editor")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "needs_review",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(
        page.work_files, "list_files", lambda job_id, user: [_job_file_row()],
    )
    monkeypatch.setattr(page.jobs, "list_access", lambda job_id: [])
    monkeypatch.setattr(page.jobs, "list_review_notes", lambda job_id, *, user_email, include_resolved=True: [])
    monkeypatch.setattr(page.jobs, "list_activity", lambda job_id, *, user_email: [])

    page._render_detail("alice@example.edu", 17)

    labels = [label for label, _kwargs in fake_st.button_calls]
    assert "Open" in labels
    assert "Remove from job" not in labels
    assert "Delete file permanently" not in labels
    assert fake_st.popovers == ["⋮"]


def test_render_detail_load_button_loads_upload_and_opens_view(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit(clicked_keys={"job_upload_load_99"})
    loaded: list[int] = []

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.session, "current_user_id", lambda: "alice@example.edu")
    monkeypatch.setattr(
        page.session,
        "open_job_file",
        lambda file_id: loaded.append(file_id) or {
            "filename": "batch.mrc",
            "total": 42,
        },
    )
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "editor")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "active",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(
        page.work_files, "list_files", lambda job_id, user: [_job_file_row()],
    )
    monkeypatch.setattr(page.jobs, "list_access", lambda job_id: [])
    monkeypatch.setattr(page.jobs, "list_review_notes", lambda job_id, *, user_email, include_resolved=True: [])
    monkeypatch.setattr(page.jobs, "list_activity", lambda job_id, *, user_email: [])

    page._render_detail("alice@example.edu", 17)

    assert loaded == [99]
    assert fake_st.session_state["switched_to"] == "views/1_View.py"
    assert fake_st.session_state["pending_toasts"] == [
        ("Opened batch.mrc — 42 records", "📂")
    ]


def test_render_detail_remove_button_soft_removes_upload(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit(clicked_keys={"job_upload_remove_99"})
    removed: list[tuple[int, str, int]] = []

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.session, "current_user_id", lambda: "alice@example.edu")
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "editor")
    monkeypatch.setattr(
        page.job_files,
        "_active_checkout",
        lambda file_id: {
            "holder_email": "alice@example.edu",
            "expires_at": "2099-01-01T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        page.work_files,
        "archive_file",
        lambda file_id, *, by, opened_version_id: removed.append(
            (file_id, by, opened_version_id)
        ),
    )
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "active",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(
        page.work_files, "list_files", lambda job_id, user: [_job_file_row()],
    )
    monkeypatch.setattr(page.jobs, "list_access", lambda job_id: [])
    monkeypatch.setattr(page.jobs, "list_review_notes", lambda job_id, *, user_email, include_resolved=True: [])
    monkeypatch.setattr(page.jobs, "list_activity", lambda job_id, *, user_email: [])

    page._render_detail("alice@example.edu", 17)

    assert removed == [(99, "alice@example.edu", 123)]
    assert fake_st.rerun_called is True
    assert fake_st.session_state["pending_toasts"] == [
        ("Archived batch.mrc.", "🗂️")
    ]


def test_render_detail_admin_archives_without_clearing_unrelated_session_work(
    monkeypatch,
):
    """Site admins use the same non-destructive removal path as editors."""
    page = _load_jobs_page(monkeypatch)
    quick_load_store = object()
    fake_st = _FakeStreamlit(
        session_state={"role": "admin", "store": quick_load_store},
        clicked_keys={"job_upload_remove_99"},
    )
    archived: list[tuple[int, str, int]] = []
    detached: list[None] = []

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.session, "current_user_id", lambda: "alice@example.edu")
    monkeypatch.setattr(
        page.session,
        "detach_loaded_batch",
        lambda file_path: detached.append(file_path),
    )
    monkeypatch.setattr(page.jobs, "get_access_role", lambda *_args: "editor")
    monkeypatch.setattr(
        page.job_files,
        "_active_checkout",
        lambda file_id: {
            "holder_email": "alice@example.edu",
            "expires_at": "2099-01-01T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        page.work_files,
        "archive_file",
        lambda file_id, *, by, opened_version_id: archived.append(
            (file_id, by, opened_version_id)
        ),
    )
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "active",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(
        page.work_files, "list_files", lambda job_id, user: [_job_file_row()],
    )
    monkeypatch.setattr(page.jobs, "list_access", lambda job_id: [])
    monkeypatch.setattr(
        page.jobs,
        "list_review_notes",
        lambda job_id, *, user_email, include_resolved=True: [],
    )
    monkeypatch.setattr(
        page.jobs, "list_activity", lambda job_id, *, user_email: []
    )

    page._render_detail("alice@example.edu", 17)

    labels = [label for label, _kwargs in fake_st.button_calls]
    assert archived == [(99, "alice@example.edu", 123)]
    assert detached == []
    assert fake_st.session_state["store"] is quick_load_store
    assert "Delete file permanently" not in labels
    assert fake_st.dialogs == []


def test_render_detail_viewer_file_actions_are_read_only(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.session, "current_user_id", lambda: "viewer@example.edu")
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "viewer")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "needs_review",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(
        page.work_files, "list_files", lambda job_id, user: [_job_file_row()],
    )
    monkeypatch.setattr(page.jobs, "list_access", lambda job_id: [])
    monkeypatch.setattr(page.jobs, "list_review_notes", lambda job_id, *, user_email, include_resolved=True: [])
    monkeypatch.setattr(page.jobs, "list_activity", lambda job_id, *, user_email: [])

    page._render_detail("viewer@example.edu", 17)

    labels = [label for label, _kwargs in fake_st.button_calls]
    assert "Open" in labels
    assert "Remove from job" not in labels
    assert "Delete file permanently" not in labels
    # Viewers get no ⋮ action menu at all.
    assert fake_st.popovers == []


def test_render_detail_loads_sharing_and_review_notes_for_job_members(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()
    access_calls: list[int] = []
    note_calls: list[tuple[int, str, bool]] = []

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "owner")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "needs_review",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(page.jobs, "list_job_uploads", lambda job_id: [])
    monkeypatch.setattr(
        page.jobs,
        "list_access",
        lambda job_id: access_calls.append(job_id) or [{
            "job_id": job_id,
            "user_email": "owner@example.edu",
            "role": "owner",
            "created_at": "2026-07-08T12:00:00Z",
        }],
    )
    monkeypatch.setattr(
        page.jobs,
        "list_review_notes",
        lambda job_id, *, user_email, include_resolved=True: note_calls.append(
            (job_id, user_email, include_resolved)
        ) or [],
    )
    monkeypatch.setattr(page.jobs, "list_activity", lambda job_id, *, user_email: [])

    page._render_detail("alice@example.edu", 17)

    assert access_calls == [17]
    assert note_calls == [(17, "alice@example.edu", True)]
    assert fake_st.subheaders == [
        "Status",
        "Files",
        "Sharing",
        "Review notes",
        "Activity",
        "Archive",
    ]
    assert [label for label, _ in fake_st.button_calls] == [
        "Back to jobs",
        "Update status",
        "Grant access",
        "Add note",
        "Archive job",
    ]


def test_render_detail_status_select_excludes_archived(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "editor")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "needs_review",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(page.jobs, "list_job_uploads", lambda job_id: [])
    monkeypatch.setattr(page.jobs, "list_access", lambda job_id: [])
    monkeypatch.setattr(
        page.jobs,
        "list_review_notes",
        lambda job_id, *, user_email, include_resolved=True: [],
    )
    monkeypatch.setattr(page.jobs, "list_activity", lambda job_id, *, user_email: [])

    page._render_detail("alice@example.edu", 17)

    status_select = next(
        call for call in fake_st.selectbox_calls if call[0] == "Workflow status"
    )
    assert "archived" not in status_select[1]


def test_render_detail_hides_archive_action_for_default_personal_uploads_job(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "owner")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": page.jobs.DEFAULT_JOB_NAME,
            "status": "active",
            "owner_email": "alice@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(page.jobs, "list_job_uploads", lambda job_id: [])
    monkeypatch.setattr(
        page.jobs,
        "list_access",
        lambda job_id: [{
            "job_id": job_id,
            "user_email": "alice@example.edu",
            "role": "owner",
            "created_at": "2026-07-08T12:00:00Z",
        }],
    )
    monkeypatch.setattr(
        page.jobs,
        "list_review_notes",
        lambda job_id, *, user_email, include_resolved=True: [],
    )
    monkeypatch.setattr(page.jobs, "list_activity", lambda job_id, *, user_email: [])

    page._render_detail("alice@example.edu", 17)

    assert "Archive" not in fake_st.subheaders
    assert "Archive job" not in [label for label, _ in fake_st.button_calls]


def test_render_detail_unauthorized_uses_generic_error_without_loading_job(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: None)
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: (_ for _ in ()).throw(AssertionError("job lookup should not happen before access check")),
    )

    page._render_detail("alice@example.edu", 17)

    assert fake_st.errors == ["Job not found or unavailable."]


def test_render_detail_missing_job_uses_same_generic_error(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "viewer")
    monkeypatch.setattr(page.jobs, "get_job", lambda job_id: None)
    monkeypatch.setattr(
        page.jobs,
        "list_job_uploads",
        lambda job_id: (_ for _ in ()).throw(AssertionError("detail render should stop on missing job")),
    )

    page._render_detail("alice@example.edu", 17)

    assert fake_st.errors == ["Job not found or unavailable."]
