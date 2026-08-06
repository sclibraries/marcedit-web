"""Tasks-page integration for recoverable Common field changes (TASK-195)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pymarc
import pytest

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


class _QuickRouterFake:
    def __init__(self, selected, *, session_state=None):
        self.selected = selected
        self.session_state = dict(session_state or {})
        self.errors = []

    def selectbox(self, label, *, options, format_func, key, **_kwargs):
        assert label == "Quick operation"
        assert self.selected in options
        self.session_state[key] = self.selected
        return self.selected

    def error(self, message):
        self.errors.append(str(message))


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


EXPECTED_QUICK_LABELS = (
    "008 form of item",
    "040 cleanup",
    "655 genre/form cleanup",
    "856 URL tools",
    "Add field",
    "Add subfield",
    "Copy field",
    "Delete field",
    "Delete subfield",
    "Find and replace",
    "Leader value",
    "Local 9xx cleanup",
    "Move or retag field",
    "OCLC 035 cleanup",
    "Remove exact duplicate fields",
    "Reorder fields by canonical tag order",
    "Set indicators",
    "Swap field occurrences",
)


def test_quick_operation_registry_is_complete_unique_and_alphabetical():
    from marcedit_web.render import tasks as tasks_render

    entries = tasks_render._quick_operation_entries()
    assert tuple(label for _identifier, label in entries) == EXPECTED_QUICK_LABELS
    assert len({identifier for identifier, _label in entries}) == 18


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        ("find-replace", ["find"]),
        ("field:delete-field", ["field", "field-export"]),
        ("batch:035-oclc", ["batch"]),
    ],
)
def test_quick_router_renders_only_the_selected_engine(monkeypatch, selected, expected):
    from marcedit_web.render import tasks as tasks_render

    calls = []
    fake_st = _QuickRouterFake(selected)
    monkeypatch.setattr(tasks_render, "st", fake_st)
    monkeypatch.setattr(tasks_render.session, "has_upload", lambda: True)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: object())
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)
    monkeypatch.setattr(
        tasks_render, "_render_quick_find_replace", lambda: calls.append("find")
    )
    monkeypatch.setattr(
        tasks_render.quick_field_changes_render,
        "render_common_field_changes",
        lambda *args, **kwargs: calls.append(("field", kwargs)),
    )
    monkeypatch.setattr(
        tasks_render,
        "_render_quick_field_change_export",
        lambda: calls.append("field-export"),
    )
    monkeypatch.setattr(
        tasks_render,
        "_render_quick_batch_operations",
        lambda kind: calls.append("batch"),
    )

    tasks_render._render_quick_ops_mode()

    actual = [call[0] if isinstance(call, tuple) else call for call in calls]
    assert actual == expected


def test_switching_quick_operation_cleans_all_preview_and_export_state(monkeypatch):
    from marcedit_web.render import tasks as tasks_render

    events = []
    find_preview = object()
    field_preview = object()
    batch_preview = object()
    field_export = {"path": "/tmp/field-export", "temporary": False}
    batch_export = {"path": "/tmp/batch-export", "temporary": False}
    fake_st = _QuickRouterFake(
        "field:add-field",
        session_state={
            tasks_render._K_QUICK_OPERATION_ACTIVE: "find-replace",
            tasks_render._K_BR_PREVIEW: find_preview,
            tasks_render._K_QFC_PREVIEW: field_preview,
            tasks_render._K_QB_PREVIEW: batch_preview,
            tasks_render._K_QFC_EXPORT: field_export,
            tasks_render._K_QB_EXPORT: batch_export,
            "br_tag": "035",
            "qb_040_agency": "MNS",
        },
    )
    monkeypatch.setattr(tasks_render, "st", fake_st)
    monkeypatch.setattr(tasks_render.session, "has_upload", lambda: True)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: object())
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: False)
    monkeypatch.setattr(
        tasks_render.batch_replace,
        "cleanup_preview",
        lambda value: events.append(("find", value)),
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "cleanup_artifact",
        lambda value: events.append(("field", value)),
    )
    monkeypatch.setattr(
        tasks_render.quick_batch,
        "cleanup_preview",
        lambda value: events.append(("batch", value)),
    )
    exports = []
    monkeypatch.setattr(
        tasks_render,
        "_cleanup_disk_backed_export",
        lambda value: exports.append(value),
    )
    monkeypatch.setattr(
        tasks_render.quick_field_changes_render,
        "render_common_field_changes",
        lambda *args, **kwargs: None,
    )

    tasks_render._render_quick_ops_mode()

    assert events == [
        ("find", find_preview),
        ("field", field_preview),
        ("batch", batch_preview),
    ]
    assert exports == [field_export, batch_export]
    assert tasks_render._K_BR_PREVIEW not in fake_st.session_state
    assert tasks_render._K_QFC_PREVIEW not in fake_st.session_state
    assert tasks_render._K_QB_PREVIEW not in fake_st.session_state
    assert tasks_render._K_QFC_EXPORT not in fake_st.session_state
    assert tasks_render._K_QB_EXPORT not in fake_st.session_state
    assert fake_st.session_state["br_tag"] == "035"
    assert fake_st.session_state["qb_040_agency"] == "MNS"


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


def test_persisted_quick_field_label_excludes_raw_selector_values(monkeypatch):
    from marcedit_web.render import tasks as tasks_render
    from marcedit_web.lib.quick_field_selector import FieldFilter, FieldSelector

    request = QuickFieldChangeRequest(
        "delete-field",
        FieldSelector(
            FieldFilter(
                "245",
                subfield_code="a",
                match_mode="contains",
                match_value="secret cataloger value",
            )
        ),
    )

    label = tasks_render._quick_field_change_label(request)

    assert "secret cataloger value" not in label
    assert "$a" not in label
    assert len(label) <= 128
    assert "Delete field" in label


def test_common_field_apply_uses_batch_admission_telemetry(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    preview = _preview(store)
    candidate = _candidate(tmp_path)
    phases = []

    class _Measure:
        def mark_error(self, value):
            phases.append(("error", value))

    class _BatchContext:
        def __enter__(self):
            return _Measure()

        def __exit__(self, *_args):
            return False

    def batch_operation(operation, *, phase, store):
        phases.append((operation, phase))
        return _BatchContext()

    monkeypatch.setattr(tasks_render, "_batch_operation", batch_operation)
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
        lambda *_args: 1,
    )
    monkeypatch.setattr(
        tasks_render.snapshot_actions,
        "record_job_snapshot",
        lambda **_kwargs: {"id": 1, "job_id": 1, "kind": "quick-field-change"},
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *_args, **_kwargs: None)

    tasks_render._apply_quick_field_change_preview(preview, preview.request)

    assert ("quick-field-change", "apply") in phases


def test_common_field_preview_uses_batch_admission_telemetry(monkeypatch, tmp_path):
    from marcedit_web.render import tasks as tasks_render

    store = _store(tmp_path)
    request = QuickFieldChangeRequest(kind="swap-field-occurrences")
    preview = _preview(store)
    phases = []

    class _Measure:
        def mark_error(self, value):
            phases.append(("error", value))

    class _BatchContext:
        def __enter__(self):
            return _Measure()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        tasks_render,
        "_batch_operation",
        lambda operation, *, phase, store: phases.append((operation, phase))
        or _BatchContext(),
    )
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "build_preview",
        lambda *_args, **_kwargs: preview,
    )

    assert tasks_render._build_quick_field_change_preview(store, request) is preview
    assert ("quick-field-change", "preview") in phases


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


@pytest.mark.parametrize(
    ("message", "job_context"),
    [
        ("Loaded batch changed since preview.", False),
        ("Sandbox operation cancelled.", False),
        ("Apply output counts differ from the preview.", False),
        ("Loaded file changed since preview.", True),
    ],
)
def test_apply_rejects_stale_or_failed_candidate_without_history(
    monkeypatch, tmp_path, message, job_context,
):
    """Tasks integration surfaces runner freshness/sandbox failures safely."""
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    store = _store(tmp_path)
    preview = _preview(
        store,
        job_file_id=10 if job_context else None,
        job_file_version_id=100 if job_context else None,
    )
    calls = []
    fake_st.session_state.update(
        {
            "job_file_id": 11 if job_context else None,
            "job_file_version_id": 101 if job_context else None,
        }
    )
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(tasks_render, "_uses_job_file_versions", lambda: job_context)
    monkeypatch.setattr(
        tasks_render.quick_field_change_runner,
        "build_apply_candidate",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or (_ for _ in ()).throw(ValueError(message)),
    )
    monkeypatch.setattr(
        tasks_render.session,
        "adopt_current_candidate",
        lambda **kwargs: calls.append("adopt"),
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

    assert fake_st.errors == [message]
    assert calls and calls[0][1]["job_file_id"] == (
        11 if job_context else None
    )
    assert calls[0][1]["job_file_version_id"] == (
        101 if job_context else None
    )
    assert "adopt" not in calls[1:]
    assert "snapshot" not in calls[1:]
    assert not fake_st.rerun_called
