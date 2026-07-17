"""Operations console behavior for durable saved-task runs (TASK-156)."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from marcedit_web.lib import operations


class _Column:
    def __init__(self, st):
        self._st = st

    def metric(self, label, value, **kwargs):
        self._st.metrics.append((label, value))

    def button(self, label, **kwargs):
        return self._st.button(label, **kwargs)

    def write(self, value):
        self._st.writes.append(str(value))

    def caption(self, value):
        self._st.captions.append(str(value))


class _FakeStreamlit:
    def __init__(self, *, clicked=(), fragments=True):
        self.session_state = {}
        self.clicked = set(clicked)
        self.rendered_text = []
        self.markdown_text = []
        self.metrics = []
        self.progress_values = []
        self.buttons = []
        self.downloads = []
        self.errors = []
        self.successes = []
        self.infos = []
        self.warnings = []
        self.captions = []
        self.writes = []
        self.fragment_intervals = []
        self.rerun_called = False
        if not fragments:
            self.fragment = None

    def _text(self, value):
        self.rendered_text.append(str(value))

    def subheader(self, value):
        self._text(value)

    def markdown(self, value, **kwargs):
        self.markdown_text.append(str(value))
        self._text(value)

    def text(self, value):
        self._text(value)

    def caption(self, value):
        self.captions.append(str(value))
        self._text(value)

    def write(self, value):
        self.writes.append(str(value))
        self._text(value)

    def info(self, value):
        self.infos.append(str(value))
        self._text(value)

    def warning(self, value):
        self.warnings.append(str(value))
        self._text(value)

    def error(self, value):
        self.errors.append(str(value))
        self._text(value)

    def success(self, value):
        self.successes.append(str(value))
        self._text(value)

    def columns(self, spec, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [_Column(self) for _ in range(count)]

    def container(self, **kwargs):
        return nullcontext()

    def expander(self, label, **kwargs):
        self._text(label)
        return nullcontext()

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return kwargs.get("key") in self.clicked

    def download_button(self, label, **kwargs):
        self.downloads.append({"label": label, **kwargs})

    def progress(self, value, **kwargs):
        self.progress_values.append(value)
        if kwargs.get("text"):
            self._text(kwargs["text"])

    def divider(self):
        return None

    def rerun(self):
        self.rerun_called = True

    def fragment(self, *, run_every):
        self.fragment_intervals.append(run_every)

        def decorate(function):
            return function

        return decorate


def _operation(operation_id=1, **changes):
    row = {
        "id": operation_id,
        "state": "queued",
        "phase": "queued",
        "submitted_by": "cataloger@example.edu",
        "submitted_at": "2026-07-17T12:00:00Z",
        "started_at": None,
        "completed_at": None,
        "processed_records": 0,
        "total_records": 60498,
        "output_records": None,
        "changed_records": None,
        "error_count": 0,
        "terminal_message": "",
        "summary": {},
        "task_names": ["Normalize 856"],
        "job_id": None,
        "job_file_id": None,
        "source_version_id": None,
        "applied_version_id": None,
        "rolled_back_version_id": None,
        "artifacts_expire_at": "2026-08-16T12:00:00Z",
        "source_label": "vendor.mrc",
        "can_cancel": True,
        "can_access_artifacts": True,
        "can_apply_result": False,
        "can_rollback_result": False,
    }
    row.update(changes)
    return row


def _wire(monkeypatch, fake_st, rows, *, artifacts=None, events=None, errors=None):
    from marcedit_web.render import operations as renderer

    monkeypatch.setattr(renderer, "st", fake_st)
    monkeypatch.setattr(
        renderer.session, "current_user_id", lambda: "cataloger@example.edu"
    )
    monkeypatch.setattr(renderer.operations, "list_visible_operations", lambda _: rows)
    monkeypatch.setattr(
        renderer.operations, "worker_health", lambda: {"available": False, "row": None}
    )
    monkeypatch.setattr(
        renderer.operations, "list_artifacts", lambda *_: list(artifacts or [])
    )
    monkeypatch.setattr(renderer.operations, "list_events", lambda *_: list(events or []))
    monkeypatch.setattr(renderer.operations, "list_errors", lambda *_: list(errors or []))
    return renderer


def _wire_sequence(monkeypatch, fake_st, row_sets):
    renderer = _wire(monkeypatch, fake_st, [])
    pending = iter(row_sets)
    monkeypatch.setattr(
        renderer.operations, "list_visible_operations", lambda _: next(pending)
    )
    return renderer


def test_empty_history_explains_where_operations_appear(monkeypatch):
    fake_st = _FakeStreamlit()
    renderer = _wire(monkeypatch, fake_st, [])
    renderer.render()
    assert any("No operations yet" in message for message in fake_st.infos)
    assert fake_st.metrics == [
        ("Running", "0"), ("Queued", "0"),
        ("Needs attention", "0"), ("Completed", "0"),
    ]


def test_running_card_shows_record_progress_and_uses_active_fragment(monkeypatch):
    fake_st = _FakeStreamlit()
    row = _operation(
        state="running", phase="processing chunk 3", processed_records=12400,
        started_at="2026-07-17T12:00:00Z",
    )
    renderer = _wire(monkeypatch, fake_st, [row])
    renderer.render()
    rendered = " ".join(fake_st.rendered_text)
    assert "12,400 of 60,498" in rendered
    assert "Processing chunk 3" in rendered
    assert fake_st.progress_values == [pytest.approx(12400 / 60498)]
    assert fake_st.fragment_intervals == ["2s"]
    assert fake_st.rerun_called is False


def test_fragment_requests_full_rerun_when_active_state_changes(monkeypatch):
    fake_st = _FakeStreamlit()
    queued = _operation(state="queued")
    running = _operation(state="running", phase="processing")
    renderer = _wire_sequence(monkeypatch, fake_st, [[queued], [running]])

    renderer.render()

    assert fake_st.rerun_called is True


def test_fragment_keeps_progress_only_updates_scoped(monkeypatch):
    fake_st = _FakeStreamlit()
    before = _operation(state="running", processed_records=100)
    after = _operation(state="running", processed_records=200)
    renderer = _wire_sequence(monkeypatch, fake_st, [[before], [after]])

    renderer.render()

    assert fake_st.rerun_called is False
    assert fake_st.progress_values == [pytest.approx(200 / 60498)]


def test_fragment_requests_full_rerun_when_operation_becomes_terminal(monkeypatch):
    fake_st = _FakeStreamlit()
    running = _operation(state="running", processed_records=100)
    completed = _operation(
        state="completed", phase="completed", processed_records=60498,
        completed_at="2026-07-17T12:10:00Z",
    )
    renderer = _wire_sequence(monkeypatch, fake_st, [[running], [completed]])

    renderer.render()

    assert fake_st.rerun_called is True


def test_fragment_requests_full_rerun_when_visible_operation_is_added(monkeypatch):
    fake_st = _FakeStreamlit()
    first = _operation(1, state="running")
    added = _operation(2, state="queued")
    renderer = _wire_sequence(monkeypatch, fake_st, [[first], [first, added]])

    renderer.render()

    assert fake_st.rerun_called is True


def test_fragment_supports_legacy_rerun_name_in_test_doubles(monkeypatch):
    fake_st = _FakeStreamlit()
    fake_st.rerun = None
    legacy_calls = []
    fake_st.experimental_rerun = lambda: legacy_calls.append(True)
    queued = _operation(state="queued")
    running = _operation(state="running")
    renderer = _wire_sequence(monkeypatch, fake_st, [[queued], [running]])

    renderer.render()

    assert legacy_calls == [True]


def test_queued_card_warns_when_worker_is_unavailable(monkeypatch):
    fake_st = _FakeStreamlit(fragments=False)
    renderer = _wire(monkeypatch, fake_st, [_operation()])
    renderer.render()
    assert fake_st.warnings == [
        "Processing service unavailable. Your operation is safely queued and "
        "will start when the worker returns."
    ]
    assert any(button["label"] == "Refresh" for button in fake_st.buttons)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            "running",
            "Processing service unavailable. This operation will restart "
            "safely from its original input when the worker returns.",
        ),
        (
            "cancelling",
            "Processing service unavailable. Cancellation will finish safely "
            "when worker recovery runs.",
        ),
    ],
)
def test_active_card_tailors_stale_worker_recovery_warning(
    monkeypatch, state, expected
):
    fake_st = _FakeStreamlit(fragments=False)
    renderer = _wire(
        monkeypatch,
        fake_st,
        [_operation(state=state, phase=state)],
    )

    renderer.render()

    assert fake_st.warnings == [expected]


def test_completed_with_errors_is_attention_and_details_are_bounded(monkeypatch):
    fake_st = _FakeStreamlit()
    row = _operation(
        state="completed", phase="completed", processed_records=60498,
        output_records=60498, changed_records=43762, error_count=19,
        completed_at="2026-07-17T12:20:00Z",
        summary={"changed_records": 43762},
    )
    retained = [
        {"record_index": 41, "task_name": "Normalize 856", "message": "Bad field"}
    ]
    timeline = [
        {
            "id": 1, "message": "Submitted",
            "actor_email": "cataloger@example.edu", "created_at": "12:00",
        },
        {
            "id": 2, "message": "Completed",
            "actor_email": "worker", "created_at": "12:20",
        },
    ]
    renderer = _wire(monkeypatch, fake_st, [row], errors=retained, events=timeline)
    renderer.render()
    assert ("Needs attention", "1") in fake_st.metrics
    rendered = " ".join(fake_st.rendered_text)
    assert "19 record errors" in rendered
    assert "Showing 1 of 19" in rendered
    assert rendered.index("12:00 · Submitted") < rendered.index("12:20 · Completed")


def test_cancel_calls_service_only_when_row_grants_permission(monkeypatch):
    fake_st = _FakeStreamlit(clicked={"operation_cancel_1"})
    renderer = _wire(monkeypatch, fake_st, [_operation()])
    calls = []
    monkeypatch.setattr(
        renderer.operations, "request_cancel",
        lambda operation_id, by: calls.append((operation_id, by)),
    )
    renderer.render()
    assert calls == [(1, "cataloger@example.edu")]
    assert fake_st.rerun_called


def test_result_bytes_are_read_only_after_prepare_download(monkeypatch, tmp_path):
    result = tmp_path / "result.mrc"
    result.write_bytes(b"result bytes")
    artifact = {
        "id": 7, "role": "result", "filename": "vendor-result.mrc",
        "file_path": str(result), "expires_at": "2099-01-01T00:00:00Z",
    }
    row = _operation(state="completed", phase="completed", completed_at="now")
    original_read = Path.read_bytes
    reads = []

    def tracked_read(path):
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)
    fake_st = _FakeStreamlit()
    renderer = _wire(monkeypatch, fake_st, [row], artifacts=[artifact])
    renderer.render()
    assert reads == []
    assert fake_st.downloads == []

    fake_st.clicked.add("operation_prepare_download_1")
    renderer.render()
    assert reads == [result]
    assert fake_st.downloads[0]["data"] == b"result bytes"


def test_large_result_is_never_materialized_for_streamlit_download(
    monkeypatch, tmp_path
):
    result = tmp_path / "large-result.mrc"
    result.write_bytes(b"small fixture")
    row = _operation(
        state="completed",
        phase="completed",
        completed_at="now",
        job_id=4,
        job_file_id=5,
        source_version_id=6,
        can_apply_result=True,
    )
    fake_st = _FakeStreamlit(clicked={"operation_prepare_download_1"})
    renderer = _wire(
        monkeypatch,
        fake_st,
        [row],
        artifacts=[{
            "role": "result",
            "filename": "large-result.mrc",
            "file_path": str(result),
        }],
    )
    monkeypatch.setattr(renderer.operations, "result_download_limit_bytes", lambda: 10)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: pytest.fail("oversized result must not be read"),
    )

    renderer.render()

    assert fake_st.downloads == []
    assert any("10-byte in-app download limit" in text for text in fake_st.warnings)
    assert "Apply as new Job version" in [
        button["label"] for button in fake_st.buttons
    ]


def test_terminal_actions_call_job_and_quick_load_services(monkeypatch, tmp_path):
    job_row = _operation(
        1, state="completed", phase="completed", completed_at="now",
        job_id=4, job_file_id=5, source_version_id=6,
        can_apply_result=True,
    )
    quick_row = _operation(2, state="completed", phase="completed", completed_at="now")
    fake_st = _FakeStreamlit(clicked={
        "operation_apply_1", "operation_reopen_result_2", "operation_reopen_input_2",
    })
    fake_st.session_state["job_file_version_id"] = 6
    source = tmp_path / "input.mrc"
    result = tmp_path / "result.mrc"
    source.write_bytes(b"input")
    result.write_bytes(b"result")
    artifacts = [
        {"role": "input", "filename": "input.mrc", "file_path": str(source)},
        {"role": "result", "filename": "result.mrc", "file_path": str(result)},
    ]
    renderer = _wire(monkeypatch, fake_st, [job_row, quick_row], artifacts=artifacts)
    calls = []
    monkeypatch.setattr(
        renderer.operation_results, "apply_job_result",
        lambda operation_id, **kwargs: calls.append(("apply", operation_id, kwargs)),
    )
    monkeypatch.setattr(
        renderer.operation_results, "reopen_quick_load",
        lambda operation_id, **kwargs: calls.append(("reopen", operation_id, kwargs)),
    )
    renderer.render()
    assert calls[0][0:2] == ("apply", 1)
    assert ("reopen", 2, {"user_email": "cataloger@example.edu", "use_result": True}) in calls
    assert ("reopen", 2, {"user_email": "cataloger@example.edu", "use_result": False}) in calls


def test_applied_job_result_offers_immutable_rollback(monkeypatch):
    row = _operation(
        state="completed", phase="completed", completed_at="now",
        job_id=4, job_file_id=5, source_version_id=6, applied_version_id=9,
        can_rollback_result=True,
    )
    fake_st = _FakeStreamlit(clicked={"operation_rollback_1"})
    fake_st.session_state["job_file_version_id"] = 9
    renderer = _wire(monkeypatch, fake_st, [row])
    calls = []
    monkeypatch.setattr(
        renderer.operation_results, "rollback_job_result",
        lambda operation_id, **kwargs: calls.append((operation_id, kwargs)),
    )

    renderer.render()

    assert calls == [(1, {
        "user_email": "cataloger@example.edu", "opened_version_id": 9,
    })]


def test_expired_or_missing_artifact_has_clear_copy(monkeypatch):
    fake_st = _FakeStreamlit()
    row = _operation(
        state="completed", phase="completed", completed_at="now",
        artifacts_expire_at="2000-01-01T00:00:00Z",
    )
    renderer = _wire(monkeypatch, fake_st, [row], artifacts=[])
    renderer.render()
    assert any("expired or is no longer available" in text for text in fake_st.captions)


def test_expired_artifact_bytes_are_not_exposed_before_cleanup(monkeypatch, tmp_path):
    result = tmp_path / "retained-but-expired.mrc"
    result.write_bytes(b"must not download")
    fake_st = _FakeStreamlit(clicked={"operation_prepare_download_1"})
    row = _operation(
        state="completed", phase="completed", completed_at="now",
        artifacts_expire_at="2000-01-01T00:00:00Z",
    )
    renderer = _wire(
        monkeypatch, fake_st, [row],
        artifacts=[{
            "role": "result", "filename": "result.mrc", "file_path": str(result),
            "expires_at": "2000-01-01T00:00:00Z",
        }],
    )
    renderer.render()
    assert fake_st.downloads == []
    assert any("expired" in text for text in fake_st.captions)


def test_cancel_control_is_hidden_without_current_permission(monkeypatch):
    fake_st = _FakeStreamlit()
    renderer = _wire(monkeypatch, fake_st, [_operation(can_cancel=False)])
    renderer.render()
    assert "Cancel" not in [button["label"] for button in fake_st.buttons]


def test_action_errors_are_shown_without_mutating_row(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(clicked={"operation_apply_1"})
    fake_st.session_state["job_file_version_id"] = 8
    row = _operation(
        state="completed", phase="completed", completed_at="now",
        job_id=4, job_file_id=5, source_version_id=8,
        can_apply_result=True,
    )
    result = tmp_path / "result.mrc"
    result.write_bytes(b"result")
    renderer = _wire(
        monkeypatch, fake_st, [row],
        artifacts=[{"role": "result", "filename": "result.mrc", "file_path": str(result)}],
    )

    def fail(*args, **kwargs):
        raise operations.OperationError("file changed since the run")

    monkeypatch.setattr(renderer.operation_results, "apply_job_result", fail)
    renderer.render()
    assert fake_st.errors == ["file changed since the run"]
    assert row["applied_version_id"] is None


def test_job_viewer_can_download_but_never_sees_mutation_controls(
    monkeypatch, tmp_path,
):
    result = tmp_path / "result.mrc"
    result.write_bytes(b"result")
    fake_st = _FakeStreamlit()
    row = _operation(
        state="completed", phase="completed", completed_at="now",
        job_id=4, job_file_id=5, source_version_id=8,
        can_access_artifacts=True, can_apply_result=False,
        can_rollback_result=False,
    )
    renderer = _wire(
        monkeypatch, fake_st, [row],
        artifacts=[{
            "role": "result", "filename": "result.mrc",
            "file_path": str(result),
        }],
    )

    renderer.render()

    labels = [button["label"] for button in fake_st.buttons]
    assert "Prepare result download" in labels
    assert "Apply as new Job version" not in labels
    assert "Roll back as a new Job version" not in labels


def test_user_controlled_task_name_is_never_rendered_as_markdown(monkeypatch):
    fake_st = _FakeStreamlit()
    task_name = "<script>alert('x')</script> **unsafe**"
    row = _operation(task_names=[task_name])
    renderer = _wire(monkeypatch, fake_st, [row])

    renderer.render()

    assert any(task_name in text for text in fake_st.rendered_text)
    assert not any("<script>" in text for text in fake_st.markdown_text)
