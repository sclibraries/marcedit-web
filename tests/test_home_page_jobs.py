"""Home page jobs workflow coverage (TASK-118 Task 5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from marcedit_web.lib import db, jobs, session, upload_persistence


HOME_PAGE = (
    Path(__file__).resolve().parents[1] / "marcedit_web" / "views" / "00_Home.py"
)


class _WidgetStateError(RuntimeError):
    """Raised when code mutates widget-owned state after instantiation."""


class _SessionState(dict[str, Any]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._widget_keys: set[str] = set()
        self._allow_widget_write = False

    def mark_widget(self, key: str) -> None:
        self._widget_keys.add(key)

    def set_widget_value(self, key: str, value: Any) -> None:
        self._allow_widget_write = True
        try:
            super().__setitem__(key, value)
        finally:
            self._allow_widget_write = False
        self.mark_widget(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self._widget_keys and not self._allow_widget_write:
            raise _WidgetStateError(
                f"st.session_state.{key} cannot be modified after widget creation"
            )
        super().__setitem__(key, value)


class _FakeContext:
    def __enter__(self) -> "_FakeContext":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeColumn:
    def __init__(self, st: "_FakeStreamlit") -> None:
        self._st = st

    def write(self, value: Any) -> None:
        self._st.writes.append(value)

    def metric(self, label: str, value: Any) -> None:
        self._st.metrics.append((label, value))

    def button(self, label: str, **kwargs: Any) -> bool:
        return self._st.button(label, **kwargs)


class _FakeStreamlit:
    def __init__(
        self,
        *,
        session_state: _SessionState | None = None,
        uploaded_file: Any = None,
        uploaded_files: dict[str, Any] | None = None,
        create_clicked: bool = False,
        clicked_keys: set[str] | None = None,
    ) -> None:
        self.session_state = session_state or _SessionState()
        self.query_params: dict[str, str] = {}
        self.uploaded_file = uploaded_file
        self.uploaded_files = uploaded_files or {}
        self.create_clicked = create_clicked
        self.clicked_keys = clicked_keys or set()
        self.writes: list[Any] = []
        self.metrics: list[tuple[str, Any]] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.dataframes: list[tuple[Any, dict[str, Any]]] = []
        self.switch_pages: list[str] = []
        self.rerun_called = False
        self.button_calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def sidebar(self) -> _FakeContext:
        return _FakeContext()

    def tabs(self, labels: list[str]) -> list[_FakeContext]:
        return [_FakeContext() for _ in labels]

    def radio(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        index = kwargs.get("index", 0)
        key = kwargs.get("key")
        if key is not None and key in self.session_state:
            return self.session_state[key]
        value = options[index]
        if key is not None:
            self.session_state.set_widget_value(key, value)
        return value

    def columns(self, spec: int | list[int]) -> list[_FakeColumn]:
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn(self) for _ in range(count)]

    def expander(self, label: str, expanded: bool = False) -> _FakeContext:
        return _FakeContext()

    def spinner(self, text: str) -> _FakeContext:
        return _FakeContext()

    def title(self, text: str) -> None:
        return None

    def header(self, text: str) -> None:
        return None

    def subheader(self, text: str) -> None:
        return None

    def caption(self, text: str) -> None:
        self.captions.append(text)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def success(self, text: str) -> None:
        self.successes.append(text)

    def warning(self, text: str) -> None:
        self.warnings.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)

    def write(self, value: Any) -> None:
        self.writes.append(value)

    def dataframe(self, data: Any, **kwargs: Any) -> None:
        self.dataframes.append((data, kwargs))

    def divider(self) -> None:
        return None

    def markdown(self, text: str) -> None:
        self.writes.append(text)

    def download_button(self, **kwargs: Any) -> None:
        return None

    def button(self, label: str, **kwargs: Any) -> bool:
        self.button_calls.append((label, kwargs))
        if kwargs.get("key") in self.clicked_keys:
            return True
        return kwargs.get("key") == "create_job_btn" and self.create_clicked

    def text_input(self, label: str, **kwargs: Any) -> str:
        if kwargs.get("key") == "new_job_name":
            return "Vendor load July"
        return ""

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        index = kwargs.get("index", 0)
        value = options[index]
        key = kwargs.get("key")
        if key is not None:
            if key not in self.session_state:
                self.session_state.set_widget_value(key, value)
            else:
                self.session_state.mark_widget(key)
        return value

    def file_uploader(self, *args: Any, **kwargs: Any) -> Any:
        key = kwargs.get("key")
        if key in self.uploaded_files:
            return self.uploaded_files[key]
        return self.uploaded_file

    def metric(self, label: str, value: Any) -> None:
        self.metrics.append((label, value))

    def switch_page(self, path: str) -> None:
        self.switch_pages.append(path)

    def rerun(self) -> None:
        self.rerun_called = True


@pytest.fixture(autouse=True)
def _schema() -> None:
    db.init_schema()


def _run_home(
    monkeypatch,
    fake_st: _FakeStreamlit,
    upload_job_ids=None,
    load_upload_ids=None,
):
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(session, "init_page", lambda: None)
    monkeypatch.setattr(session, "current_user_id", lambda: "cataloger@example.edu")
    monkeypatch.setattr(session, "has_upload", lambda: False)
    monkeypatch.setattr(session, "current_filename", lambda: None)
    monkeypatch.setattr(session, "record_count", lambda: 0)
    monkeypatch.setattr(session, "current_store", lambda: None)
    monkeypatch.setattr(session, "current_raw_bytes", lambda: None)
    def _handle_upload(uploaded):
        if upload_job_ids is not None:
            upload_job_ids.append(fake_st.session_state.get("current_job_id"))
        return {
            "filename": getattr(uploaded, "name", "upload.mrc"),
            "total": 1,
            "malformed": 0,
            "error": None,
        }

    monkeypatch.setattr(session, "handle_upload", _handle_upload)
    def _load_persisted_upload(upload_id):
        if load_upload_ids is not None:
            load_upload_ids.append(upload_id)
        return {
            "filename": "vendor.mrc",
            "total": 1,
            "malformed": 0,
            "error": None,
        }

    monkeypatch.setattr(session, "load_persisted_upload", _load_persisted_upload)

    spec = importlib.util.spec_from_file_location("task118_home_page", HOME_PAGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quick_load_uses_default_personal_job(monkeypatch):
    """Quick Load should not force catalogers through shared job workflow."""
    default = jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState({"quick_load_mode": True})

    _run_home(monkeypatch, _FakeStreamlit(session_state=state, create_clicked=False))

    assert state["current_job_id"] == default["id"]


def test_quick_load_resets_selected_shared_job_to_default(monkeypatch):
    """Quick Load must attach uploads to the personal default even after shared work."""
    default = jobs.ensure_default_job("cataloger@example.edu")
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    state = _SessionState(
        {"quick_load_mode": True, "current_job_id": shared["id"]}
    )

    _run_home(monkeypatch, _FakeStreamlit(session_state=state, create_clicked=False))

    assert state["current_job_id"] == default["id"]


def test_job_workspace_upload_uses_selected_job(monkeypatch):
    """Uploading from Job Workspace must attach the file to the selected job."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
        }
    )
    upload_job_ids = []
    uploaded = type("Upload", (), {"name": "vendor.mrc"})()

    fake_st = _FakeStreamlit(
        session_state=state,
        uploaded_files={"home_job_workspace_upload": uploaded},
    )

    _run_home(
        monkeypatch,
        fake_st,
        upload_job_ids=upload_job_ids,
    )

    assert upload_job_ids == [shared["id"]]
    assert fake_st.query_params["start"] == "jobs"


def test_job_workspace_url_overrides_quick_load_state(monkeypatch):
    """A shared workspace URL should reopen Job Workspace after Quick Load use."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    state = _SessionState(
        {
            "quick_load_mode": True,
            "current_job_id": shared["id"],
        }
    )
    fake_st = _FakeStreamlit(session_state=state)
    fake_st.query_params["start"] = "jobs"

    _run_home(monkeypatch, fake_st)

    assert state["quick_load_mode"] is False
    assert fake_st.query_params["start"] == "jobs"


def test_job_workspace_shows_files_attached_to_selected_job(monkeypatch):
    """The selected job should visibly list its attached MARC files."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    upload_persistence.record_upload(
        user="cataloger@example.edu",
        filename="vendor.mrc",
        file_path="/tmp/vendor.mrc",
        record_count=12,
        file_bytes=345,
        job_id=shared["id"],
    )
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
        }
    )
    fake_st = _FakeStreamlit(session_state=state)

    _run_home(monkeypatch, fake_st)

    assert fake_st.dataframes == []
    assert any("vendor.mrc" in str(value) for value in fake_st.writes)


def test_job_workspace_loads_selected_file_from_home(monkeypatch):
    """Home's file list should let catalogers load a specific job file."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    upload_persistence.record_upload(
        user="cataloger@example.edu",
        filename="vendor.mrc",
        file_path="/tmp/vendor.mrc",
        record_count=12,
        file_bytes=345,
        job_id=shared["id"],
    )
    upload_id = jobs.list_job_uploads(shared["id"])[0]["id"]
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
        }
    )
    fake_st = _FakeStreamlit(
        session_state=state,
        clicked_keys={f"home_job_upload_load_{upload_id}"},
    )
    loaded: list[int] = []
    _run_home(monkeypatch, fake_st, load_upload_ids=loaded)

    assert loaded == [upload_id]
    assert fake_st.switch_pages == ["views/1_View.py"]


def test_job_workspace_soft_removes_selected_file_from_home(monkeypatch):
    """Home's file list should allow editors to remove a file from a job."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    upload_persistence.record_upload(
        user="cataloger@example.edu",
        filename="vendor.mrc",
        file_path="/tmp/vendor.mrc",
        record_count=12,
        file_bytes=345,
        job_id=shared["id"],
    )
    upload_id = jobs.list_job_uploads(shared["id"])[0]["id"]
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
        }
    )
    fake_st = _FakeStreamlit(
        session_state=state,
        clicked_keys={f"home_job_upload_remove_{upload_id}"},
    )
    removed: list[tuple[int, str, bool]] = []
    monkeypatch.setattr(
        jobs,
        "remove_upload",
        lambda upload_id, *, by, delete_file=False: removed.append(
            (upload_id, by, delete_file)
        ),
    )

    _run_home(monkeypatch, fake_st)

    assert removed == [(upload_id, "cataloger@example.edu", False)]
    assert fake_st.rerun_called is True


def test_job_workspace_delete_file_only_for_original_uploader(monkeypatch):
    """Hard delete should only be visible to the cataloger who uploaded the file."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    upload_persistence.record_upload(
        user="other@example.edu",
        filename="vendor.mrc",
        file_path="/tmp/vendor.mrc",
        record_count=12,
        file_bytes=345,
        job_id=shared["id"],
    )
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
        }
    )
    fake_st = _FakeStreamlit(session_state=state)

    _run_home(monkeypatch, fake_st)

    assert "Delete file" not in [label for label, _kwargs in fake_st.button_calls]


def test_create_job_uses_rerun_handoff_instead_of_mutating_widget_state(monkeypatch):
    """Create job must not write current_job_id after the widget is live."""
    default = jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState(
        {"current_job_id": default["id"], "home_start_path": "Job Workspace"}
    )

    module = _run_home(
        monkeypatch,
        _FakeStreamlit(session_state=state, create_clicked=True),
    )

    pending_job_id = state[module._PENDING_CURRENT_JOB_ID]
    assert pending_job_id != default["id"]
    assert state["current_job_id"] == default["id"]
