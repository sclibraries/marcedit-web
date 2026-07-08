"""Jobs page render helpers (TASK-118)."""

from __future__ import annotations

import importlib
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

    def button(self, label: str, **kwargs: Any) -> bool:
        self._st.button_calls.append((label, kwargs))
        return False


class _FakeStreamlit:
    def __init__(self, *, session_state: dict[str, Any] | None = None, toggle_value: bool = False) -> None:
        self.session_state = session_state or {}
        self.toggle_value = toggle_value
        self.titles: list[str] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.subheaders: list[str] = []
        self.writes: list[Any] = []
        self.dataframes: list[tuple[Any, dict[str, Any]]] = []
        self.button_calls: list[tuple[str, dict[str, Any]]] = []
        self.toggle_calls: list[tuple[str, dict[str, Any]]] = []
        self.selectbox_calls: list[tuple[str, Any, dict[str, Any]]] = []
        self.text_input_calls: list[tuple[str, dict[str, Any]]] = []
        self.text_area_calls: list[tuple[str, dict[str, Any]]] = []
        self.rerun_called = False

    def title(self, text: str) -> None:
        self.titles.append(text)

    def caption(self, text: str) -> None:
        self.captions.append(text)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)

    def toggle(self, label: str, **kwargs: Any) -> bool:
        self.toggle_calls.append((label, kwargs))
        return self.toggle_value

    def container(self, **kwargs: Any) -> _FakeContainer:
        return _FakeContainer(self)

    def columns(self, spec: list[int]) -> list[_FakeColumn]:
        return [_FakeColumn(self) for _ in spec]

    def button(self, label: str, **kwargs: Any) -> bool:
        self.button_calls.append((label, kwargs))
        return False

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


def _load_jobs_page(monkeypatch):
    import marcedit_web.views.B_Jobs as page

    monkeypatch.setattr(page.session, "init_page", lambda: None)
    return importlib.reload(page)


def test_status_label_is_cataloger_readable(monkeypatch):
    page = _load_jobs_page(monkeypatch)

    assert page._status_label("needs_review") == "Needs review"
    assert page._status_label("ready_to_load") == "Ready to load"


def test_format_size_uses_human_units(monkeypatch):
    page = _load_jobs_page(monkeypatch)

    assert page._format_size(999) == "999 B"
    assert page._format_size(1536) == "1.5 KB"
    assert page._format_size(2 * 1024 * 1024) == "2.0 MB"


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
        page.jobs,
        "list_job_uploads",
        lambda job_id: upload_calls.append(job_id) or [{
            "filename": "batch.mrc",
            "record_count": 42,
            "file_bytes": 2048,
            "uploaded_at": "2026-07-08T12:00:00Z",
            "active": 1,
        }],
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
    assert len(fake_st.dataframes) == 2


def test_render_detail_loads_sharing_and_review_notes_for_job_members(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()
    access_calls: list[int] = []
    note_calls: list[tuple[int, str, bool]] = []

    monkeypatch.setattr(page, "st", fake_st)
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
    monkeypatch.setattr(page.jobs, "get_access_role", lambda job_id, user_email: "viewer")
    monkeypatch.setattr(page.jobs, "get_job", lambda job_id: None)
    monkeypatch.setattr(
        page.jobs,
        "list_job_uploads",
        lambda job_id: (_ for _ in ()).throw(AssertionError("detail render should stop on missing job")),
    )

    page._render_detail("alice@example.edu", 17)

    assert fake_st.errors == ["Job not found or unavailable."]
