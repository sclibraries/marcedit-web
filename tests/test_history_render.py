"""History page renderer (TASK-143).

Why these tests exist: the app's memory ceiling is the point of
TASK-142 — the timeline must list snapshots metadata-only (no
download_button until the user prepares one), and the export banner
must not hold batch bytes in session_state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymarc

from marcedit_web.lib.record_store import RecordStore


class _Column:
    def __init__(self, st):
        self._st = st

    def button(self, label, **kwargs):
        self._st.buttons.append({"label": label, **kwargs})
        return kwargs.get("key") in self._st.clicked_keys

    def download_button(self, label, **kwargs):
        self._st.download_buttons.append({"label": label, **kwargs})

    def caption(self, message):
        self._st.captions.append(str(message))

    def write(self, value):
        self._st.writes.append(str(value))

    def markdown(self, value):
        self._st.markdowns.append(str(value))

    def metric(self, label, value):
        self._st.metrics.append((label, value))


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.clicked_keys: set[str] = set()
        self.buttons: list[dict] = []
        self.download_buttons: list[dict] = []
        self.captions: list[str] = []
        self.markdowns: list[str] = []
        self.writes: list[str] = []
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.metrics: list[tuple] = []
        self.tables: list = []
        self.dividers = 0
        self.rerun_called = False

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return kwargs.get("key") in self.clicked_keys

    def download_button(self, label=None, **kwargs):
        self.download_buttons.append({"label": label, **kwargs})

    def caption(self, message):
        self.captions.append(str(message))

    def markdown(self, message):
        self.markdowns.append(str(message))

    def info(self, message):
        self.infos.append(str(message))

    def warning(self, message):
        self.warnings.append(str(message))

    def error(self, message):
        self.errors.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def subheader(self, message):
        self.markdowns.append(str(message))

    def metric(self, label, value):
        self.metrics.append((label, value))

    def table(self, data):
        self.tables.append(data)

    def columns(self, spec, **kwargs):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Column(self) for _ in range(n)]

    def divider(self):
        self.dividers += 1

    def rerun(self):
        self.rerun_called = True


def _record():
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(tag="001", data="hist-ui"))
    return record


def _store(tmp_path):
    return RecordStore.from_records(
        [_record()], tmp_dir=tmp_path / "records", filename="hist.mrc"
    )


def _history(monkeypatch, fake_st):
    from marcedit_web.render import history

    monkeypatch.setattr(history, "st", fake_st)
    return history


def _snapshot_row(tmp_path, snapshot_id=1, with_files=True):
    before = tmp_path / f"{snapshot_id}-before.mrc"
    after = tmp_path / f"{snapshot_id}-after.mrc"
    if with_files:
        data = _record().as_marc()
        before.write_bytes(data)
        after.write_bytes(data)
    return {
        "id": snapshot_id,
        "job_id": 3,
        "user_email": "cat@smith.edu",
        "kind": "quick-replace",
        "label": "Find/replace 245$a",
        "before_path": str(before),
        "after_path": str(after),
        "summary_json": json.dumps({"changed_count": 1}),
        "created_at": "2026-07-10T12:00:00Z",
    }


def _wire_loaded(monkeypatch, history, store, rows):
    monkeypatch.setattr(
        history.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(history.session, "has_upload", lambda: True)
    monkeypatch.setattr(history.session, "current_store", lambda: store)
    monkeypatch.setattr(
        history.session, "current_filename", lambda: "hist.mrc"
    )
    monkeypatch.setattr(
        history.provenance, "list_snapshots", lambda job_id: rows
    )
    monkeypatch.setattr(history.jobs, "list_job_uploads", lambda job_id: [])
    monkeypatch.setattr(
        history.jobs,
        "get_job",
        lambda job_id: {"id": 3, "name": history.jobs.DEFAULT_JOB_NAME},
    )


def test_timeline_lists_snapshots_metadata_only(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    rows = [_snapshot_row(tmp_path)]
    _wire_loaded(monkeypatch, history, _store(tmp_path), rows)
    fake_st.session_state["current_job_id"] = 3

    history.render()

    joined = " ".join(fake_st.markdowns)
    assert "Find/replace 245$a" in joined
    # Memory guard: nothing materializes bytes until the user asks.
    assert fake_st.download_buttons == []


def test_missing_snapshot_files_degrade_gracefully(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    rows = [_snapshot_row(tmp_path, with_files=False)]
    _wire_loaded(monkeypatch, history, _store(tmp_path), rows)
    fake_st.session_state["current_job_id"] = 3

    history.render()  # must not raise

    assert any(
        "no longer available" in c for c in fake_st.captions
    )


def test_export_banner_two_step_prepare_then_download(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    store = _store(tmp_path)
    _wire_loaded(monkeypatch, history, store, [])
    fake_st.session_state["current_job_id"] = 3
    monkeypatch.setattr(
        history.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "exp")
    )
    (tmp_path / "exp").mkdir()

    history.render()
    assert fake_st.download_buttons == []  # not prepared yet

    fake_st.clicked_keys.add("history_export_prepare")
    history.render()
    assert fake_st.rerun_called
    export = fake_st.session_state[history.K_EXPORT]
    assert Path(export["path"]).exists()

    fake_st.clicked_keys.clear()
    fake_st.rerun_called = False
    history.render()
    assert len(fake_st.download_buttons) == 1
    assert fake_st.download_buttons[0]["file_name"] == export["filename"]


def test_no_upload_lists_recent_files(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    monkeypatch.setattr(
        history.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(history.session, "has_upload", lambda: False)
    monkeypatch.setattr(
        history.jobs,
        "list_job_summaries",
        lambda user: [{"id": 3, "name": "Vendor load"}],
    )
    monkeypatch.setattr(
        history.jobs,
        "list_job_uploads",
        lambda job_id: [
            {
                "id": 11,
                "filename": "old.mrc",
                "record_count": 5,
                "uploaded_at": "2026-07-01T09:00:00Z",
            }
        ],
    )

    history.render()

    assert any("old.mrc" in w for w in fake_st.writes)
    assert any(b["label"] == "Load" for b in fake_st.buttons)


def test_anonymous_user_sees_sign_in_notice(monkeypatch):
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    monkeypatch.setattr(history.session, "current_user_id", lambda: "")
    monkeypatch.setattr(history, "is_anonymous", lambda user: True)

    history.render()

    assert fake_st.infos and "Sign in" in fake_st.infos[0]
