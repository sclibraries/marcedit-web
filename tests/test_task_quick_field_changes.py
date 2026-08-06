"""Tasks-page integration for recoverable Common field changes (TASK-195)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pymarc

from marcedit_web.lib.record_store import RecordStore
from marcedit_web.lib.quick_field_changes import QuickFieldChangeRequest
from marcedit_web.lib.quick_field_change_runner import QuickFieldChangePreview


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.warnings: list[str] = []
        self.rerun_called = False

    def error(self, message):
        self.errors.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def warning(self, message):
        self.warnings.append(str(message))

    def rerun(self):
        self.rerun_called = True


def _record() -> pymarc.Record:
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(tag="001", data="quick-field"))
    return record


def _store(tmp_path) -> RecordStore:
    return RecordStore.from_records(
        [_record()],
        tmp_dir=tmp_path / "records",
        filename="quick-field.mrc",
    )


def _tasks_render(monkeypatch, fake_st):
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    return tasks_render


def _preview(store, *, job_file_id=None, job_file_version_id=None):
    request = QuickFieldChangeRequest(kind="swap-field-occurrences")
    return QuickFieldChangePreview(
        request=request,
        request_json="request",
        store_id=id(store),
        store_revision=store.revision,
        record_count=store.count(),
        changed_count=1,
        skipped_count=0,
        job_file_id=job_file_id,
        job_file_version_id=job_file_version_id,
    )


def _candidate(tmp_path):
    workdir = tmp_path / "candidate"
    workdir.mkdir()
    output = workdir / "candidate.mrc"
    output.write_bytes(b"candidate")
    return SimpleNamespace(
        output_path=output,
        workdir=workdir,
        changed_count=1,
        skipped_count=0,
    )


def test_quick_ops_mounts_common_field_changes_between_existing_quick_flows(
    monkeypatch,
):
    from marcedit_web.render import tasks as tasks_render

    calls = []
    monkeypatch.setattr(tasks_render.session, "has_upload", lambda: True)
    monkeypatch.setattr(
        tasks_render, "_render_quick_find_replace", lambda: calls.append("find")
    )
    monkeypatch.setattr(
        tasks_render.quick_field_changes_render,
        "render_common_field_changes",
        lambda *args, **kwargs: calls.append(("field", kwargs)),
    )
    monkeypatch.setattr(
        tasks_render, "_render_quick_batch_operations", lambda: calls.append("batch")
    )
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)

    tasks_render._render_quick_ops_mode()

    assert calls[0] == "find"
    assert calls[1][0] == "field"
    assert calls[1][1]["job_file_id"] is None
    assert calls[1][1]["job_file_version_id"] is None
    assert calls[2] == "batch"


def test_job_file_quick_field_change_creates_recoverable_version(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    preview = _preview(store, job_file_id=10, job_file_version_id=100)
    candidate = _candidate(tmp_path)
    adoption = []
    events = []

    fake_st.session_state.update(
        {"job_file_id": 10, "job_file_version_id": 100, "current_job_id": 3}
    )
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render.session, "current_user_id", lambda: "cat@example.edu")
    monkeypatch.setattr(tasks_render.session, "current_filename", lambda: "quick-field.mrc")
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: True)
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "build_apply_candidate",
        lambda *args, **kwargs: candidate,
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "cleanup_artifact",
        lambda value: events.append(("cleanup", value)),
    )
    monkeypatch.setattr(
        tasks_render.session,
        "adopt_current_candidate",
        lambda **kwargs: adoption.append(kwargs) or {"id": 20, "version_number": 2},
    )
    monkeypatch.setattr(
        tasks_render, "audit_event", lambda kind, **kwargs: events.append((kind, kwargs))
    )

    tasks_render._apply_quick_field_change_preview(preview, preview.request)

    assert adoption[0]["source_kind"] == "quick-field-change"
    assert adoption[0]["summary"]["operation_kind"] == "swap-field-occurrences"
    assert "marc" not in str(adoption[0]["summary"]).lower()
    assert any(event[0] == "quick-field-change-applied" for event in events)
    assert fake_st.rerun_called


def test_quick_load_quick_field_change_stages_snapshot_and_export(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    preview = _preview(store)
    candidate = _candidate(tmp_path)
    snapshots = []
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render.session, "current_user_id", lambda: "cat@example.edu")
    monkeypatch.setattr(tasks_render.session, "current_filename", lambda: "quick-field.mrc")
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "build_apply_candidate",
        lambda *args, **kwargs: candidate,
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "adopt_candidate_to_store",
        lambda current, value: 1,
    )
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **kwargs: snapshots.append(
            {**kwargs, "before_bytes": kwargs["before_path"].read_bytes()}
        )
        or {"id": 7, "job_id": 3, "kind": "quick-field-change"},
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *args, **kwargs: None)

    tasks_render._apply_quick_field_change_preview(preview, preview.request)

    assert snapshots[0]["kind"] == "quick-field-change"
    assert snapshots[0]["before_bytes"]
    export = fake_st.session_state[tasks_render._K_QFC_EXPORT]
    assert export["snapshot_id"] == 7
    assert Path(export["path"]).exists()
    assert fake_st.rerun_called


def test_quick_field_change_apply_failure_does_not_adopt_or_record_history(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    preview = _preview(store)
    calls = []
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "build_apply_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("sandbox cancelled")),
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "adopt_candidate_to_store",
        lambda *args, **kwargs: calls.append("adopt"),
    )
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **kwargs: calls.append("snapshot"),
    )

    tasks_render._apply_quick_field_change_preview(preview, preview.request)

    assert calls == []
    assert fake_st.errors == ["sandbox cancelled"]
    assert not fake_st.rerun_called


def test_quick_field_change_adoption_failure_cleans_candidate_and_keeps_history(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    preview = _preview(store)
    candidate = _candidate(tmp_path)
    cleaned = []
    snapshots = []
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "build_apply_candidate",
        lambda *args, **kwargs: candidate,
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "cleanup_artifact",
        lambda value: cleaned.append(value),
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "adopt_candidate_to_store",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("output mismatch")),
    )
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **kwargs: snapshots.append(kwargs),
    )

    tasks_render._apply_quick_field_change_preview(preview, preview.request)

    assert cleaned == [candidate]
    assert snapshots == []
    assert fake_st.errors == ["output mismatch"]
    assert not fake_st.rerun_called
