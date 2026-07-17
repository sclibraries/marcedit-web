"""Tests for Tasks-page export naming (TASK-141)."""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace


class _Spinner:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _RunStatus(_Spinner):
    def update(self, **_kwargs):
        pass


def _tasks_render():
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    return tasks_render


class _FakeColumn:
    def __init__(self, st):
        self._st = st

    def metric(self, label, value):
        self._st.metrics.append((label, value))

    def button(self, label, **kwargs):
        self._st.buttons.append({"label": label, **kwargs})
        return False

    def download_button(self, **kwargs):
        self._st.download_buttons.append(kwargs)

    def caption(self, message):
        self._st.captions.append(str(message))


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.clicked_keys: set[str] = set()
        self.buttons: list[dict] = []
        self.captions: list[str] = []
        self.download_buttons: list[dict] = []
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.markdowns: list[str] = []
        self.metrics: list[tuple[str, object]] = []
        self.page_links: list[dict] = []
        self.successes: list[str] = []

    def divider(self):
        pass

    def markdown(self, message):
        self.markdowns.append(str(message))

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn(self) for _ in range(count)]

    def caption(self, message):
        self.captions.append(str(message))

    def info(self, message):
        self.infos.append(str(message))

    def error(self, message):
        self.errors.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def page_link(self, page, **kwargs):
        self.page_links.append({"page": page, **kwargs})

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return kwargs.get("key") in self.clicked_keys

    def download_button(self, **kwargs):
        self.download_buttons.append(kwargs)

    def spinner(self, _message):
        return _Spinner()

    def status(self, _message, **_kwargs):
        return _RunStatus()

    def write(self, _message):
        pass

    def text_input(self, _label, *, key, **_kwargs):
        return self.session_state.get(key, "")

    def text_area(self, _label, *, key, **_kwargs):
        return self.session_state.get(key, "")

    def multiselect(self, _label, *, options, default, **_kwargs):
        return list(default)

    def rerun(self):
        self.rerun_called = True


def test_file_exports_are_labeled_and_download_from_retained_paths(
    monkeypatch, tmp_path,
):
    """The durable export path, not mutable task output, is delivery evidence."""
    from marcedit_web.render import job_files as job_files_render

    fake_st = _FakeStreamlit()
    fake_st.rerun_called = False
    retained = tmp_path / "retained.mrc"
    retained.write_bytes(b"retained-export")
    mutable_output = tmp_path / "task-output.mrc"
    mutable_output.write_bytes(b"mutable-preview")
    exports = [
        {
            "id": export_id,
            "job_file_id": 9,
            "version_id": 20 + export_id,
            "version_number": export_id,
            "purpose": f"Purpose {state}",
            "description": "Retained delivery",
            "filename": f"{state}.mrc",
            "file_path": str(retained if state == "ready" else mutable_output),
            "record_count": 7,
            "state": state,
            "created_by": "owner@example.edu",
            "created_at": "2026-07-15T12:00:00Z",
            "loaded_destination": "EDS" if state == "loaded" else None,
            "loaded_external_id": "load-7" if state == "loaded" else None,
            "loaded_note": "Accepted" if state == "loaded" else None,
            "loaded_by": "editor@example.edu" if state == "loaded" else None,
            "loaded_at": "2026-07-15T13:00:00Z" if state == "loaded" else None,
        }
        for export_id, state in enumerate(
            ("draft", "ready", "superseded", "loaded"), start=1
        )
    ]
    monkeypatch.setattr(job_files_render, "st", fake_st, raising=False)
    monkeypatch.setattr(
        job_files_render.job_files,
        "list_exports",
        lambda file_id, user: exports,
    )

    job_files_render.render_file_exports(
        {"id": 9, "display_name": "deletes.mrc", "access_role": "editor"},
        user="editor@example.edu",
        opened_version_id=22,
    )

    rendered = " ".join(fake_st.markdowns + fake_st.captions)
    assert all(state in rendered for state in ("Draft", "Ready", "Superseded", "Loaded"))
    assert fake_st.download_buttons == []
    assert not any(button["label"] == "Mark complete" for button in fake_st.buttons)

    fake_st.clicked_keys.add("file_export_prepare_2")
    job_files_render.render_file_exports(
        {"id": 9, "display_name": "deletes.mrc", "access_role": "editor"},
        user="editor@example.edu",
        opened_version_id=22,
    )
    fake_st.clicked_keys.clear()
    job_files_render.render_file_exports(
        {"id": 9, "display_name": "deletes.mrc", "access_role": "editor"},
        user="editor@example.edu",
        opened_version_id=22,
    )

    ready_download = next(
        button for button in fake_st.download_buttons
        if button["file_name"] == "ready.mrc"
    )
    assert ready_download["data"] == Path(retained).read_bytes()


def test_file_export_form_passes_required_labels_and_manual_load_audit(
    monkeypatch, tmp_path,
):
    from marcedit_web.render import job_files as job_files_render

    fake_st = _FakeStreamlit()
    fake_st.rerun_called = False
    fake_st.session_state.update({
        "file_export_purpose_9": "EDS deletion load",
        "file_export_description_9": "July withdrawal",
        "file_export_filename_9": "routledge-deletes.mrc",
        "file_export_destination_4": "EDS",
        "file_export_external_id_4": "load-2026-07-15",
        "file_export_note_4": "Accepted",
    })
    export_path = tmp_path / "ready.mrc"
    export_path.write_bytes(b"ready")
    ready = {
        "id": 4,
        "job_file_id": 9,
        "version_id": 22,
        "version_number": 3,
        "purpose": "EDS deletion load",
        "description": "July withdrawal",
        "filename": "routledge-deletes.mrc",
        "file_path": str(export_path),
        "record_count": 7,
        "state": "ready",
        "created_by": "owner@example.edu",
        "created_at": "2026-07-15T12:00:00Z",
        "loaded_destination": None,
        "loaded_external_id": None,
        "loaded_note": None,
        "loaded_by": None,
        "loaded_at": None,
    }
    created = []
    loaded = []
    monkeypatch.setattr(job_files_render, "st", fake_st, raising=False)
    monkeypatch.setattr(
        job_files_render.job_files, "list_exports", lambda *_args: [ready]
    )
    monkeypatch.setattr(
        job_files_render.job_files,
        "create_export",
        lambda **kwargs: created.append(kwargs) or ready,
    )
    monkeypatch.setattr(
        job_files_render.job_files,
        "mark_export_loaded",
        lambda export_id, **kwargs: loaded.append((export_id, kwargs)) or ready,
    )
    monkeypatch.setattr(
        job_files_render,
        "_active_checkout",
        lambda file_id: {"holder_email": "editor@example.edu"},
    )
    fake_st.clicked_keys.update({"file_export_create_9", "file_export_loaded_4"})

    job_files_render.render_file_exports(
        {
            "id": 9,
            "display_name": "deletes.mrc",
            "access_role": "editor",
            "archived_at": None,
            "current_version_id": 22,
        },
        user="editor@example.edu",
        opened_version_id=22,
    )

    assert created == [{
        "file_id": 9,
        "opened_version_id": 22,
        "user_email": "editor@example.edu",
        "purpose": "EDS deletion load",
        "description": "July withdrawal",
        "filename": "routledge-deletes.mrc",
    }]
    assert loaded == [(4, {
        "by": "editor@example.edu",
        "destination": "EDS",
        "external_id": "load-2026-07-15",
        "note": "Accepted",
    })]


def test_create_export_controls_require_current_active_holder(
    monkeypatch, tmp_path,
):
    """Read access never exposes the checkout-bound export mutation."""
    from marcedit_web.render import job_files as job_files_render

    export_path = tmp_path / "retained.mrc"
    export_path.write_bytes(b"retained")
    retained = {
        "id": 4,
        "job_file_id": 9,
        "version_id": 22,
        "version_number": 3,
        "purpose": "Prior export",
        "description": "",
        "filename": "retained.mrc",
        "file_path": str(export_path),
        "record_count": 7,
        "state": "draft",
        "created_by": "owner@example.edu",
        "created_at": "2026-07-15T12:00:00Z",
        "loaded_destination": None,
        "loaded_external_id": None,
        "loaded_note": None,
        "loaded_by": None,
        "loaded_at": None,
    }
    monkeypatch.setattr(
        job_files_render.job_files, "list_exports", lambda *_args: [retained]
    )
    cases = (
        ("viewer", None, 22, None),
        ("editor", None, 22, {"holder_email": "owner@example.edu"}),
        (
            "editor",
            "2026-07-15T13:00:00Z",
            22,
            {"holder_email": "editor@example.edu"},
        ),
        ("editor", None, 21, {"holder_email": "editor@example.edu"}),
    )

    for role, archived_at, opened_version_id, checkout in cases:
        fake_st = _FakeStreamlit()
        fake_st.rerun_called = False
        monkeypatch.setattr(job_files_render, "st", fake_st, raising=False)
        monkeypatch.setattr(
            job_files_render, "_active_checkout", lambda _file_id, row=checkout: row
        )

        job_files_render.render_file_exports(
            {
                "id": 9,
                "display_name": "deletes.mrc",
                "access_role": role,
                "archived_at": archived_at,
                "current_version_id": 22,
            },
            user="editor@example.edu",
            opened_version_id=opened_version_id,
        )

        assert "Create export" not in [button["label"] for button in fake_st.buttons]
        assert "Prior export" in " ".join(fake_st.markdowns)


def test_export_filename_keeps_source_name_but_adds_operation_suffix():
    tasks_render = _tasks_render()

    filename = tasks_render._export_filename("source-file.mrc", "tasks")

    assert filename != "source-file.mrc"
    assert re.fullmatch(r"source-file_tasks_\d{8}_\d{6}\.mrc", filename)


def test_export_filename_defaults_when_source_missing():
    tasks_render = _tasks_render()

    filename = tasks_render._export_filename(None, "quickbatch")

    assert re.fullmatch(r"transformed_quickbatch_\d{8}_\d{6}\.mrc", filename)


def test_history_location_caption_points_to_history_page_when_available():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(7) == (
        "Rollback and before/after downloads are available on the "
        "History page."
    )


def test_history_location_caption_explains_unsigned_fallback():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(None) == (
        "Rollback history is only available for signed-in job files. "
        "Download the updated MARC file below."
    )


def test_disk_backed_export_retains_job_version_history_reference(tmp_path):
    """A versioned job mutation must advertise its durable History entry."""
    tasks_render = _tasks_render()
    source = tmp_path / "source.mrc"
    source.write_bytes(b"updated")

    export = tasks_render._disk_backed_export(
        filename="updated.mrc",
        source_path=source,
        snapshot=None,
        job_file_version={"id": 22},
        prefix="task-151-history-",
    )

    assert export["job_file_version_id"] == 22


def test_batch_operation_uses_shared_gate_and_telemetry(monkeypatch, tmp_path):
    tasks_render = _tasks_render()
    source_path = tmp_path / "source.mrc"
    source_path.write_bytes(b"batch-bytes")
    store = SimpleNamespace(count=lambda: 100_000, path=source_path)
    events = []

    @contextmanager
    def _slot(operation):
        events.append(("slot", operation))
        yield

    @contextmanager
    def _measure(operation, **dimensions):
        events.append(("measure", operation, dimensions))
        yield

    monkeypatch.setattr(tasks_render.batch_runtime, "batch_slot", _slot)
    monkeypatch.setattr(
        tasks_render.batch_runtime, "measure_operation", _measure
    )

    with tasks_render._batch_operation(
        "quick-batch", phase="preview", store=store
    ):
        events.append(("body",))

    assert events == [
        ("slot", "quick-batch"),
        (
            "measure",
            "quick-batch",
            {
                "phase": "preview",
                "records": 100_000,
                "bytes": len(b"batch-bytes"),
            },
        ),
        ("body",),
    ]


def test_run_panel_explains_durable_background_processing(monkeypatch):
    """Catalogers know queued work survives leaving the Tasks page."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)

    tasks_render._render_run_panel([], Path("/unused"))

    rendered = " ".join(fake_st.captions)
    assert "queued" in rendered.lower()
    assert "leave this tab open" not in rendered.lower()


def test_saved_task_submission_preserves_order_and_exact_job_version(
    monkeypatch, tmp_path,
):
    """Queued work snapshots the selected order and opened immutable version."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    fake_st.session_state.update({"job_file_id": 9, "job_file_version_id": 21})
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "owner@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.editor,
        "parse_user_task_file",
        lambda path: {"body": f"body for {path.stem}"},
    )
    submitted = []
    monkeypatch.setattr(
        tasks_render.operation_submission,
        "submit_job_task_run",
        lambda **kwargs: submitted.append(kwargs) or {"id": 42},
    )
    monkeypatch.setattr(
        tasks_render.sandbox,
        "run_tasks_subprocess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Streamlit must not execute queued tasks")
        ),
    )

    tasks_render._submit_queued_run(["second", "first"], tmp_path)

    assert submitted[0]["user_email"] == "owner@smith.edu"
    assert submitted[0]["file_id"] == 9
    assert submitted[0]["source_version_id"] == 21
    assert [spec.name for spec in submitted[0]["task_specs"]] == [
        "second", "first",
    ]
    assert [spec.body for spec in submitted[0]["task_specs"]] == [
        "body for second", "body for first",
    ]
    assert fake_st.successes == [
        "Operation queued. You can safely leave this page."
    ]
    assert fake_st.page_links == [{
        "page": "views/D_Operations.py",
        "label": "View operation 42",
        "icon": ":material/pending_actions:",
    }]


def test_saved_task_submission_copies_current_quick_load_source(
    monkeypatch, tmp_path,
):
    """Quick Load submissions capture durable bytes and user-facing metadata."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    source = tmp_path / "current.mrc"
    source.write_bytes(b"records")
    store = SimpleNamespace(path=source, count=lambda: 17)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "owner@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.session, "current_filename", lambda: "vendor.mrc"
    )
    monkeypatch.setattr(
        tasks_render.editor,
        "parse_user_task_file",
        lambda _path: {"body": "record.remove_fields('9XX')"},
    )
    submitted = []
    monkeypatch.setattr(
        tasks_render.operation_submission,
        "submit_quick_load_task_run",
        lambda **kwargs: submitted.append(kwargs) or {"id": 43},
    )

    tasks_render._submit_queued_run(["cleanup"], tmp_path)

    assert submitted[0]["source_path"] == source
    assert submitted[0]["filename"] == "vendor.mrc"
    assert submitted[0]["record_count"] == 17
    assert [spec.name for spec in submitted[0]["task_specs"]] == ["cleanup"]


def test_saved_task_run_panel_queues_without_keep_tab_open_warning(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    fake_st.clicked_keys.add("tasks_run_btn")
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    queued = []
    monkeypatch.setattr(
        tasks_render,
        "_submit_queued_run",
        lambda selection, tasks_dir: queued.append((selection, tasks_dir)),
    )
    registered = [SimpleNamespace(name="cleanup")]

    tasks_render._render_run_panel(registered, tmp_path)

    assert queued == [(["cleanup"], tmp_path)]
    copy = " ".join(fake_st.captions)
    assert "leave this tab open" not in copy.lower()
    assert "queue" in copy.lower()
