"""Home page jobs workflow coverage (TASK-118 Task 5)."""

from __future__ import annotations

import importlib.util
import sys
import types
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

    def markdown(self, text: str) -> None:
        self._st.writes.append(text)

    def metric(self, label: str, value: Any) -> None:
        self._st.metrics.append((label, value))

    def button(self, label: str, **kwargs: Any) -> bool:
        return self._st.button(label, **kwargs)

    def columns(self, spec: int | list[Any], **kwargs: Any) -> list["_FakeColumn"]:
        return self._st.columns(spec, **kwargs)

    def popover(self, label: str, **kwargs: Any) -> _FakeContext:
        self._st.popovers.append(label)
        return _FakeContext()


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
        self.selected_dataframe_rows: list[int] = []
        self.switch_pages: list[str] = []
        self.rerun_called = False
        self.button_calls: list[tuple[str, dict[str, Any]]] = []
        self.download_buttons: list[dict[str, Any]] = []
        self.popovers: list[str] = []
        self.column_calls: list[tuple[Any, dict[str, Any]]] = []

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

    def columns(self, spec: int | list[Any], **kwargs: Any) -> list[_FakeColumn]:
        self.column_calls.append((spec, kwargs))
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn(self) for _ in range(count)]

    def expander(self, label: str, expanded: bool = False) -> _FakeContext:
        return _FakeContext()

    def container(self, **kwargs: Any) -> _FakeContext:
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
        return {"selection": {"rows": self.selected_dataframe_rows}}

    def divider(self) -> None:
        return None

    def markdown(self, text: str) -> None:
        self.writes.append(text)

    def download_button(self, **kwargs: Any) -> None:
        self.download_buttons.append(kwargs)
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

    def cache_data(self, *args: Any, **kwargs: Any):
        # marcedit_web.render's __init__ decorates a loader with
        # @st.cache_data(show_spinner=False) at import time; pass through.
        if args and callable(args[0]) and not kwargs:
            return args[0]

        def _decorator(func):
            return func

        return _decorator


@pytest.fixture(autouse=True)
def _schema() -> None:
    db.init_schema()


def _run_home(
    monkeypatch,
    fake_st: _FakeStreamlit,
    upload_job_ids=None,
    load_upload_ids=None,
    has_upload: bool = False,
    upload_error: str | None = None,
    upload_total: int = 1,
    raw_bytes_calls=None,
):
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setattr(session, "init_page", lambda: None)
    monkeypatch.setattr(session, "current_user_id", lambda: "cataloger@example.edu")
    monkeypatch.setattr(session, "has_upload", lambda: has_upload)
    monkeypatch.setattr(session, "current_filename", lambda: None)
    monkeypatch.setattr(session, "record_count", lambda: 0)
    monkeypatch.setattr(session, "current_store", lambda: None)

    def _current_raw_bytes():
        if raw_bytes_calls is not None:
            raw_bytes_calls.append(1)
        return b"fake-mrc-bytes"

    monkeypatch.setattr(session, "current_raw_bytes", _current_raw_bytes)
    def _handle_upload(uploaded):
        if upload_job_ids is not None:
            upload_job_ids.append(fake_st.session_state.get("current_job_id"))
        return {
            "filename": getattr(uploaded, "name", "upload.mrc"),
            "total": 0 if upload_error else upload_total,
            "malformed": 0,
            "error": upload_error,
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
        uploaded_files={"home_job_workspace_upload_0": uploaded},
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
    """The selected job should list its files as aligned single-line table rows."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    upload_persistence.record_upload(
        user="cataloger@example.edu",
        filename="vendor.mrc",
        file_path="/tmp/vendor.mrc",
        record_count=1204,
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

    from marcedit_web.render import job_files

    assert fake_st.dataframes == []
    assert "**Filename**" in fake_st.writes
    assert "**Records**" in fake_st.writes
    assert "**Size**" in fake_st.writes
    assert "**Uploaded**" in fake_st.writes
    assert "**Status**" in fake_st.writes
    # Actions live in per-row widgets now; a header over them is noise.
    assert "Actions" not in fake_st.writes
    assert any("vendor.mrc" in str(value) for value in fake_st.writes)
    assert "1,204" in fake_st.writes
    assert "345 B" in fake_st.writes
    assert ":green[● Current]" in fake_st.writes
    # Single-height rows: every grid row must be vertically centered.
    grid_calls = [
        kwargs
        for spec, kwargs in fake_st.column_calls
        if spec == job_files.UPLOADS_GRID
    ]
    assert grid_calls, "expected header + file rows to use UPLOADS_GRID"
    assert all(k.get("vertical_alignment") == "center" for k in grid_calls)


def test_uploaded_at_renders_human_readable(monkeypatch):
    """Catalogers scan upload dates; raw ISO strings defeat that."""
    from marcedit_web.render import job_files

    assert job_files.format_uploaded_at("2026-07-01T09:14:32Z") == "Jul 1, 2026 09:14"
    assert job_files.format_uploaded_at("not-a-date") == "not-a-date"


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

    labels = [label for label, _kwargs in fake_st.button_calls]
    assert "Delete file permanently" not in labels
    # Owner can still soft-remove, so the ⋮ menu renders with Remove only.
    assert fake_st.popovers == ["⋮"]
    assert "Remove from job" in labels


def test_job_workspace_delete_detaches_loaded_batch(monkeypatch):
    """Deleting the loaded file must drop the session batch (TASK-128).

    Otherwise the rerun's "Loaded batch" footer reads the just-unlinked
    file and crashes with FileNotFoundError.
    """
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
    loaded_store = types.SimpleNamespace(path=Path("/tmp/vendor.mrc"))
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
            "store": loaded_store,
        }
    )
    fake_st = _FakeStreamlit(
        session_state=state,
        clicked_keys={f"home_job_upload_delete_{upload_id}"},
    )
    monkeypatch.setattr(
        jobs,
        "remove_upload",
        lambda upload_id, *, by, delete_file=False: None,
    )

    _run_home(monkeypatch, fake_st)

    assert state["store"] is None
    assert fake_st.rerun_called is True


def test_job_workspace_viewer_sees_load_but_no_action_menu(monkeypatch):
    """Viewers may load files but must not see remove/delete affordances."""
    shared = jobs.create_job("owner@example.edu", "Vendor load June")
    jobs.grant_access(
        shared["id"], "cataloger@example.edu", "viewer", by="owner@example.edu"
    )
    upload_persistence.record_upload(
        user="owner@example.edu",
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
    fake_st = _FakeStreamlit(session_state=state)

    _run_home(monkeypatch, fake_st)

    assert fake_st.popovers == []
    load_keys = [
        kwargs.get("key")
        for label, kwargs in fake_st.button_calls
        if label == "Load"
    ]
    assert f"home_job_upload_load_{upload_id}" in load_keys


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


# ---------------------------------------------------------------------------
# TASK-131 — release uploader widget memory after ingest
# ---------------------------------------------------------------------------
# Streamlit keeps the full uploaded file in server RAM for as long as it
# sits in the file_uploader widget (the memory pattern implicated in the
# TASK-117 overnight outage). After a successful ingest the batch lives
# on disk in the RecordStore, so Home must rotate the uploader key (the
# fresh widget is empty → RAM released) and rerun, rendering feedback
# from the persisted summary instead of re-ingesting on every rerun.


def test_quick_load_upload_releases_widget_after_ingest(monkeypatch):
    """A successful Quick Load ingest must rotate the uploader key and rerun."""
    jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState({"quick_load_mode": True})
    uploaded = type("Upload", (), {"name": "big.mrc"})()
    fake_st = _FakeStreamlit(
        session_state=state,
        uploaded_files={"home_quick_load_upload_0": uploaded},
    )

    _run_home(monkeypatch, fake_st)

    assert state["home_quick_upload_nonce"] == 1
    assert fake_st.rerun_called
    assert state["home_quick_upload_summary"]["filename"] == "big.mrc"


def test_quick_load_feedback_survives_widget_release(monkeypatch):
    """The rerun after ingest still shows the summary without re-ingesting."""
    jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState(
        {
            "quick_load_mode": True,
            "home_quick_upload_nonce": 1,
            "home_quick_upload_summary": {
                "filename": "big.mrc",
                "total": 1,
                "malformed": 0,
                "error": None,
            },
        }
    )
    upload_calls: list = []
    fake_st = _FakeStreamlit(session_state=state)

    _run_home(monkeypatch, fake_st, upload_job_ids=upload_calls, has_upload=True)

    assert upload_calls == []
    assert any("Loaded" in s for s in fake_st.successes)
    assert not fake_st.rerun_called


def test_quick_load_rejected_upload_keeps_widget_and_shows_error(monkeypatch):
    """A rejected upload must stay in the widget next to its error message."""
    jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState({"quick_load_mode": True})
    uploaded = type("Upload", (), {"name": "toobig.mrc"})()
    fake_st = _FakeStreamlit(
        session_state=state,
        uploaded_files={"home_quick_load_upload_0": uploaded},
    )

    _run_home(
        monkeypatch,
        fake_st,
        upload_error="File exceeds the 200 MB limit.",
    )

    assert state.get("home_quick_upload_nonce", 0) == 0
    assert not fake_st.rerun_called
    assert any("File exceeds" in e for e in fake_st.errors)


def test_job_workspace_upload_releases_widget_after_ingest(monkeypatch):
    """A successful Job Workspace ingest must rotate its uploader key too."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
        }
    )
    uploaded = type("Upload", (), {"name": "vendor.mrc"})()
    fake_st = _FakeStreamlit(
        session_state=state,
        uploaded_files={"home_job_workspace_upload_0": uploaded},
    )

    _run_home(monkeypatch, fake_st)

    assert state["home_job_upload_nonce"] == 1
    assert fake_st.rerun_called
    assert state["home_job_upload_summary"]["filename"] == "vendor.mrc"
    # The banner must be attributable to the job it was uploaded to,
    # or a later job selection inherits it (review finding).
    assert state["home_job_upload_summary"]["job_id"] == shared["id"]


def test_quick_load_zero_record_upload_shows_error_without_rotation(monkeypatch):
    """A 0-record file must show 'No records found', not silently vanish.

    Rotating on total==0 would rerun into a state where has_upload() is
    False (empty store), suppressing all feedback — the file disappears
    from the widget with no explanation (review finding on TASK-131).
    """
    jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState({"quick_load_mode": True})
    uploaded = type("Upload", (), {"name": "empty.mrc"})()
    fake_st = _FakeStreamlit(
        session_state=state,
        uploaded_files={"home_quick_load_upload_0": uploaded},
    )

    _run_home(monkeypatch, fake_st, upload_total=0)

    assert state.get("home_quick_upload_nonce", 0) == 0
    assert not fake_st.rerun_called
    assert any("No records found" in e for e in fake_st.errors)


def test_job_workspace_does_not_render_quick_load_summary(monkeypatch):
    """A Quick Load banner under a job's uploader implies the file was
    attached to that job — it never was (review finding on TASK-131)."""
    jobs.ensure_default_job("cataloger@example.edu")
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    state = _SessionState({"quick_load_mode": True})
    uploaded = type("Upload", (), {"name": "batch.mrc"})()
    fake1 = _FakeStreamlit(
        session_state=state,
        uploaded_files={"home_quick_load_upload_0": uploaded},
    )
    _run_home(monkeypatch, fake1)  # quick-load success stores its summary

    # Next run: cataloger switches to Job Workspace with a shared job.
    state.set_widget_value("home_start_path", "Job Workspace")
    state["quick_load_mode"] = False
    state["current_job_id"] = shared["id"]
    fake2 = _FakeStreamlit(session_state=state)

    _run_home(monkeypatch, fake2, has_upload=True)

    assert not any("Loaded" in s for s in fake2.successes)


def test_job_summary_only_renders_for_its_own_job(monkeypatch):
    """The job upload banner must follow its job, not the page."""
    shared = jobs.create_job("cataloger@example.edu", "Vendor load June")
    other = jobs.create_job("cataloger@example.edu", "Vendor load July")
    summary = {
        "filename": "vendor.mrc",
        "total": 12,
        "malformed": 0,
        "error": None,
        "job_id": other["id"],
    }
    state = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": shared["id"],
            "home_start_path": "Job Workspace",
            "home_job_upload_summary": summary,
        }
    )
    fake_st = _FakeStreamlit(session_state=state)

    _run_home(monkeypatch, fake_st, has_upload=True)

    assert not any("Loaded" in s for s in fake_st.successes)

    state2 = _SessionState(
        {
            "quick_load_mode": False,
            "current_job_id": other["id"],
            "home_start_path": "Job Workspace",
            "home_job_upload_summary": summary,
        }
    )
    fake_st2 = _FakeStreamlit(session_state=state2)

    _run_home(monkeypatch, fake_st2, has_upload=True)

    assert any("Loaded" in s for s in fake_st2.successes)


# ---------------------------------------------------------------------------
# TASK-135 — gate batch download materialization
# ---------------------------------------------------------------------------


def test_home_render_does_not_materialize_batch_bytes(monkeypatch):
    """Rendering Home with a loaded batch must not rebuild the full MRC
    blob — to_mrc_bytes on every rerun re-creates the O(file) RAM
    footprint TASK-131/132 removed (TASK-117 review finding)."""
    jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState({"quick_load_mode": True})
    calls: list = []
    fake_st = _FakeStreamlit(session_state=state)

    _run_home(monkeypatch, fake_st, has_upload=True, raw_bytes_calls=calls)

    assert calls == []
    assert fake_st.download_buttons == []


def test_prepare_download_materializes_once_and_renders_button(monkeypatch):
    jobs.ensure_default_job("cataloger@example.edu")
    state = _SessionState({"quick_load_mode": True})
    calls: list = []
    fake_st = _FakeStreamlit(
        session_state=state,
        clicked_keys={"home_prepare_download"},
    )

    _run_home(monkeypatch, fake_st, has_upload=True, raw_bytes_calls=calls)

    prepare_keys = [kwargs.get("key") for _, kwargs in fake_st.button_calls]
    assert "home_prepare_download" in prepare_keys
    assert len(calls) == 1
    assert len(fake_st.download_buttons) == 1
