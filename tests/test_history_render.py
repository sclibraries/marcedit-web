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

    def write(self, value):
        self.writes.append(str(value))

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

    def text_area(self, label, **kwargs):
        return ""

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


def test_restore_invalidates_prepared_export(monkeypatch, tmp_path):
    """A restore must drop any already-prepared export.

    "Restore pre-change version" swaps the loaded batch without adding a
    snapshot, so the staleness guard (which only compares snapshot
    counts) never fires. An export prepared before the restore would
    otherwise keep being offered and would serve pre-restore bytes
    (found in TASK-143 runtime verification).
    """
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    store = _store(tmp_path)
    row = _snapshot_row(tmp_path)
    _wire_loaded(monkeypatch, history, store, [row])
    fake_st.session_state["current_job_id"] = 3

    export_dir = tmp_path / "exp"
    export_dir.mkdir()
    export_path = export_dir / "hist_export.mrc"
    export_path.write_bytes(b"stale-bytes")
    fake_st.session_state[history.K_EXPORT] = {
        "path": str(export_path),
        "filename": "hist_export.mrc",
        "snapshot_count": 1,  # matches len(rows) — staleness guard won't fire
    }

    restore_path = tmp_path / "restore.mrc"
    restore_path.write_bytes(_record().as_marc())
    monkeypatch.setattr(
        history.provenance, "restore_path", lambda snapshot_id: restore_path
    )
    monkeypatch.setattr(
        history.session,
        "replace_current_store_from_path",
        lambda path, *, filename, job_id: None,
    )

    fake_st.clicked_keys.add(f"snapshot_restore_{row['id']}")
    history.render()

    assert history.K_EXPORT not in fake_st.session_state
    assert not export_path.exists()


def test_export_invalidated_when_loaded_file_switches(monkeypatch, tmp_path):
    """A prepared export must not survive loading a different file.

    Staleness was previously detected only by comparing snapshot counts.
    Loading a different file via Home upload, Jobs Load, or the History
    recent-files Load does not add a snapshot, and two files can share a
    snapshot count (commonly 0 == 0) — so the banner would keep showing
    "Current file: B.mrc" while the download button served A's bytes
    under A's name (found in TASK-143 final review).
    """
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    store = _store(tmp_path)
    _wire_loaded(monkeypatch, history, store, [])
    fake_st.session_state["current_job_id"] = 3
    monkeypatch.setattr(
        history.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "exp")
    )
    (tmp_path / "exp").mkdir()

    fake_st.clicked_keys.add("history_export_prepare")
    history.render()
    export = fake_st.session_state[history.K_EXPORT]
    export_path = Path(export["path"])
    assert export_path.exists()

    # Simulate switching to a different file with the same snapshot
    # count (0 changes for both — the old guard alone can't catch this).
    fake_st.clicked_keys.clear()
    fake_st.rerun_called = False
    monkeypatch.setattr(
        history.session, "current_filename", lambda: "other.mrc"
    )

    history.render()

    assert fake_st.download_buttons == []
    assert any(
        b["label"] == "Prepare export of current file"
        for b in fake_st.buttons
    )
    assert history.K_EXPORT not in fake_st.session_state
    assert not export_path.exists()


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


def test_job_file_history_is_scoped_and_legacy_history_is_separate(
    monkeypatch, tmp_path
):
    """The review page presents immutable file history before unlinked legacy rows."""
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    store = _store(tmp_path)
    legacy = [_snapshot_row(tmp_path, snapshot_id=77)]
    _wire_loaded(monkeypatch, history, store, legacy)
    fake_st.session_state.update({
        "current_job_id": 3,
        "job_file_id": 9,
        "job_file_version_id": 12,
    })
    original = tmp_path / "v1.mrc"
    current = tmp_path / "v2.mrc"
    data = _record().as_marc()
    original.write_bytes(data)
    current.write_bytes(data)
    monkeypatch.setattr(
        history.job_files,
        "get_file",
        lambda file_id, user: {
            "id": file_id,
            "job_id": 3,
            "display_name": "deletes.mrc",
            "status": "needs_review",
            "current_version_id": 12,
            "access_role": "editor",
        },
    )
    monkeypatch.setattr(
        history.job_files,
        "list_versions",
        lambda file_id, user: [
            {
                "id": 11,
                "job_file_id": 9,
                "version_number": 1,
                "parent_version_id": None,
                "file_path": str(original),
                "source_kind": "original",
                "label": "deletes.mrc",
                "created_by": "owner@example.edu",
                "created_at": "2026-07-10T10:00:00Z",
                "approval_kind": "self-approved",
                "approved_by": "owner@example.edu",
                "approved_at": "2026-07-10T10:05:00Z",
                "summary_json": "{}",
                "validation_json": "{}",
            },
            {
                "id": 12,
                "job_file_id": 9,
                "version_number": 2,
                "parent_version_id": 11,
                "file_path": str(current),
                "source_kind": "restore",
                "label": "Restore version 1",
                "created_by": "editor@example.edu",
                "created_at": "2026-07-10T11:00:00Z",
                "approval_kind": "peer-approved",
                "approved_by": "owner@example.edu",
                "approved_at": "2026-07-10T11:05:00Z",
                "summary_json": "{}",
                "validation_json": "{}",
            },
        ],
    )
    monkeypatch.setattr(
        history.jobs,
        "list_review_notes",
        lambda job_id, *, user_email, job_file_id: [{
            "id": 5,
            "note": "Check leader",
            "job_file_version_id": 12,
            "author_email": "owner@example.edu",
            "created_at": "2026-07-10T11:10:00Z",
            "resolved": 0,
        }],
    )
    monkeypatch.setattr(history, "_can_restore_file", lambda *_args: True)
    rendered_exports = []
    monkeypatch.setattr(
        history.job_files_render,
        "render_file_exports",
        lambda file_row, **kwargs: rendered_exports.append((file_row, kwargs)),
    )

    history.render()

    rendered = " ".join(fake_st.markdowns + fake_st.captions + fake_st.writes)
    assert "Immutable version history" in rendered
    assert "Restore version 1" in rendered
    assert "self-approved" in rendered
    assert "peer-approved" in rendered
    assert "Check leader" in rendered
    assert "Legacy job history" in rendered
    assert any(button["label"] == "Restore as new version" for button in fake_st.buttons)
    assert any(button["label"] == "Approve current" for button in fake_st.buttons)
    assert any(button["label"] == "Add review note" for button in fake_st.buttons)
    assert "1 recorded change" in rendered
    assert rendered_exports == [(
        {
            "id": 9,
            "job_id": 3,
            "display_name": "deletes.mrc",
            "status": "needs_review",
            "current_version_id": 12,
            "access_role": "editor",
        },
        {"user": "cat@smith.edu", "opened_version_id": 12},
    )]


def test_historical_restore_control_requires_checkout_holder(monkeypatch, tmp_path):
    """Read access alone never exposes the immutable restore mutation."""
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    path = tmp_path / "v1.mrc"
    path.write_bytes(_record().as_marc())
    version = {
        "id": 11,
        "version_number": 1,
        "parent_version_id": None,
        "file_path": str(path),
        "source_kind": "original",
        "label": "deletes.mrc",
        "created_by": "owner@example.edu",
        "created_at": "2026-07-10T10:00:00Z",
        "approval_kind": None,
        "summary_json": "{}",
        "validation_json": "{}",
    }

    history._render_file_version_entry(
        version,
        {11: version},
        [],
        is_current=False,
        can_restore=False,
    )

    assert "Restore as new version" not in [row["label"] for row in fake_st.buttons]


def test_checkout_holder_sees_historical_restore_control(monkeypatch, tmp_path):
    """An editor holding the file checkout may restore with the opened token."""
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    path = tmp_path / "v1.mrc"
    path.write_bytes(_record().as_marc())
    version = {
        "id": 11,
        "version_number": 1,
        "parent_version_id": None,
        "file_path": str(path),
        "source_kind": "original",
        "label": "deletes.mrc",
        "created_by": "owner@example.edu",
        "created_at": "2026-07-10T10:00:00Z",
        "approval_kind": None,
        "summary_json": "{}",
        "validation_json": "{}",
    }

    history._render_file_version_entry(
        version,
        {11: version},
        [],
        is_current=False,
        can_restore=True,
    )

    assert "Restore as new version" in [row["label"] for row in fake_st.buttons]


def test_restore_permission_checks_role_holder_and_exact_opened_version(
    monkeypatch,
):
    """Restore visibility derives from role, active holder, and opened version."""
    fake_st = _FakeStreamlit()
    history = _history(monkeypatch, fake_st)
    from marcedit_web.render import job_files as job_files_render

    fake_st.session_state["job_file_version_id"] = 12
    file_row = {
        "id": 9,
        "current_version_id": 12,
        "access_role": "editor",
    }
    monkeypatch.setattr(
        job_files_render,
        "_active_checkout",
        lambda _file_id: {"holder_email": "editor@example.edu"},
    )

    assert history._can_restore_file(file_row, "editor@example.edu") is True
    assert history._can_restore_file(file_row, "other@example.edu") is False
    assert history._can_restore_file(
        {**file_row, "access_role": "viewer"}, "editor@example.edu"
    ) is False
    fake_st.session_state["job_file_version_id"] = 11
    assert history._can_restore_file(file_row, "editor@example.edu") is False


def test_history_return_for_review_only_renders_for_in_progress(monkeypatch):
    """A loaded version token cannot expose Return from new/changes states."""
    for status in ("new", "changes_requested", "approved"):
        fake_st = _FakeStreamlit()
        fake_st.session_state["job_file_version_id"] = 12
        history = _history(monkeypatch, fake_st)

        history._render_file_transition_controls(
            {
                "id": 9,
                "job_id": 3,
                "current_version_id": 12,
                "access_role": "editor",
                "status": status,
            },
            "editor@example.edu",
        )

        assert "Return for review" not in [row["label"] for row in fake_st.buttons]
