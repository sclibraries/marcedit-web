"""Tasks workspace permissions for correcting shared tasks (TASK-172)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from marcedit_web.lib import task_builder, task_db
from marcedit_web.lib.task_builder import Operation


class _Column:
    def __init__(self, streamlit):
        self.streamlit = streamlit

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def button(self, label, **kwargs):
        self.streamlit.buttons.append((label, kwargs))
        return False

    def caption(self, value):
        self.streamlit.captions.append(value)

    def markdown(self, *args, **kwargs):
        return None

    def metric(self, *args, **kwargs):
        return None

    def empty(self):
        return None


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.buttons: list[tuple[str, dict]] = []
        self.captions: list[str] = []
        self.text_inputs: list[tuple[str, dict]] = []
        self.radios: list[tuple[str, dict]] = []

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [_Column(self) for _ in range(count)]

    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs))
        return False

    def text_input(self, label, **kwargs):
        self.text_inputs.append((label, kwargs))
        return kwargs.get("value", "")

    def radio(self, label, options, **kwargs):
        self.radios.append((label, kwargs))
        return options[kwargs.get("index", 0)]

    def file_uploader(self, *args, **kwargs):
        return None

    def subheader(self, *args, **kwargs):
        return None

    def caption(self, value):
        self.captions.append(value)

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def divider(self):
        return None

    def rerun(self):
        raise AssertionError("unexpected rerun")

    def error(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None


def _tasks_render(monkeypatch, fake_st):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    return tasks_render


@pytest.fixture
def tasks_render(monkeypatch):
    return _tasks_render(monkeypatch, _FakeStreamlit())


def _form_row(*, owner: str, visibility: str, row_id: int = 1) -> dict:
    rendered = task_builder.render_ops_to_python(
        [Operation(kind="delete-tag", params={"tag": "029"})]
    )
    return {
        "id": row_id,
        "owner_email": owner,
        "name": "cleanup",
        "description": "Remove vendor field",
        "body": rendered["body"],
        "extra_imports": "\n".join(rendered["imports"]),
        "visibility": visibility,
        "updated_at": "2026-07-22T12:00:00Z",
    }


def _code_row(*, owner: str, visibility: str, row_id: int = 1) -> dict:
    row = _form_row(owner=owner, visibility=visibility, row_id=row_id)
    row["body"] = "record.remove_fields('029')\n"
    return row


def test_shared_form_task_is_editable_by_non_owner(tasks_render):
    row = _form_row(owner="owner@example.edu", visibility="shared")
    assert tasks_render._can_edit_visible_task(
        row, "editor@example.edu", is_admin=False
    ) is True


def test_shared_code_task_requires_admin_for_non_owner(tasks_render):
    row = _code_row(owner="owner@example.edu", visibility="shared")
    assert tasks_render._can_edit_visible_task(
        row, "editor@example.edu", is_admin=False
    ) is False
    assert tasks_render._can_edit_visible_task(
        row, "admin@example.edu", is_admin=True
    ) is True


def test_private_task_is_not_editable_by_non_owner(tasks_render):
    row = _form_row(owner="owner@example.edu", visibility="private")
    assert tasks_render._can_edit_visible_task(
        row, "editor@example.edu", is_admin=True
    ) is False


@pytest.mark.parametrize("visibility", ["private", "shared"])
def test_owner_retains_edit_access(tasks_render, visibility):
    row = _code_row(owner="owner@example.edu", visibility=visibility)
    assert tasks_render._can_edit_visible_task(
        row, "owner@example.edu", is_admin=False
    ) is True


def test_shared_form_list_uses_row_ids_and_hides_owner_controls(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    rows = [
        _form_row(owner="first@example.edu", visibility="shared", row_id=17),
        _form_row(owner="second@example.edu", visibility="shared", row_id=18),
    ]
    fake_st.session_state[tasks_render.K_EDITOR_OPEN] = False
    monkeypatch.setattr(
        tasks_render.task_db,
        "count_visible",
        lambda user: {"own": 0, "shared_from_others": 2},
    )
    monkeypatch.setattr(tasks_render.task_db, "list_own_tasks", lambda user: [])
    monkeypatch.setattr(
        tasks_render.task_db, "list_visible_tasks", lambda user: rows
    )
    monkeypatch.setattr(tasks_render, "_render_ai_draft_panel", lambda: None)

    tasks_render._render_build_mode(
        Path("/tmp/tasks"), False, "editor@example.edu", {}
    )

    edit_keys = [
        kwargs["key"] for label, kwargs in fake_st.buttons if label == "Edit"
    ]
    assert edit_keys == ["edit_17", "edit_18"]
    assert not {label for label, _ in fake_st.buttons}.intersection(
        {"Share", "Unshare", "Delete"}
    )


def _save_state(tasks_render, row: dict, *, actor: str, mode: str = "form"):
    parsed = task_builder.parse_ops_from_source(row["body"])
    tasks_render.st.session_state.update(
        {
            tasks_render.K_EDITOR_OPEN: True,
            tasks_render.K_EDITOR_NAME: row["name"],
            tasks_render.K_EDITOR_NAME_INPUT: "hacked-name",
            tasks_render.K_EDITOR_DESCRIPTION: row["description"],
            tasks_render.K_EDITOR_DESCRIPTION_INPUT: "Corrected description",
            tasks_render.K_EDITOR_MODE: mode,
            tasks_render.K_EDITOR_VISIBILITY: "private",
            tasks_render.K_EDITOR_BODY: row["body"],
            tasks_render.K_EDITOR_OPS: [
                op.to_dict() for op in parsed.get("ops", [])
            ],
            tasks_render.K_EDITOR_ORIGINAL_NAME: row["name"],
            tasks_render.K_EDITOR_OWNER: row["owner_email"],
            tasks_render.K_EDITOR_SNAPSHOT: task_db.task_edit_snapshot(row),
            tasks_render.K_EDITOR_COLLABORATIVE: row["owner_email"] != actor,
            tasks_render.K_EDITOR_FROM_AI_DRAFT: False,
            tasks_render.K_EDITOR_AI_DRAFT_REVIEW: None,
        }
    )


def _wire_save(monkeypatch, tasks_render, *, actor: str, is_admin: bool):
    updates: list[dict] = []
    owner_saves: list[dict] = []
    deletes: list[tuple] = []
    materialized: list[tuple] = []
    reloads: list[tuple] = []
    audits: list[tuple] = []
    monkeypatch.setattr(tasks_render.session, "current_user_id", lambda: actor)
    monkeypatch.setattr(
        tasks_render.task_admin, "is_admin", lambda user: is_admin
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "update_shared_task",
        lambda **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: owner_saves.append(kwargs),
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "delete_task",
        lambda *args: deletes.append(args),
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "materialize_to_dir",
        lambda *args: materialized.append(args),
    )
    monkeypatch.setattr(
        tasks_render.tasks,
        "load_user_tasks",
        lambda *args, **kwargs: reloads.append((args, kwargs)),
    )
    monkeypatch.setattr(
        tasks_render,
        "audit_event",
        lambda *args, **kwargs: audits.append((args, kwargs)),
    )
    return updates, owner_saves, deletes, materialized, reloads, audits


def test_collaborator_save_preserves_owner_name_and_visibility(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    row = _form_row(owner="owner@example.edu", visibility="shared")
    _save_state(tasks_render, row, actor="editor@example.edu")
    updates, owner_saves, deletes, materialized, reloads, audits = _wire_save(
        monkeypatch, tasks_render, actor="editor@example.edu", is_admin=False
    )

    tasks_render._save_callback(Path("/tmp/tasks"))

    assert updates[0]["actor"] == "editor@example.edu"
    assert updates[0]["owner"] == "owner@example.edu"
    assert updates[0]["name"] == "cleanup"
    assert "visibility" not in updates[0]
    assert owner_saves == []
    assert deletes == []
    assert materialized == [("editor@example.edu", Path("/tmp/tasks"))]
    assert len(reloads) == 1
    assert audits[-1][1]["task_owner"] == "owner@example.edu"
    assert audits[-1][1]["collaborative_edit"] is True
    assert fake_st.session_state[tasks_render.K_EDITOR_OPEN] is False


def test_stale_collaborator_save_stays_inline_without_reload(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    row = _form_row(owner="owner@example.edu", visibility="shared")
    _save_state(tasks_render, row, actor="editor@example.edu")
    updates, _saves, _deletes, materialized, reloads, _audits = _wire_save(
        monkeypatch, tasks_render, actor="editor@example.edu", is_admin=False
    )

    def stale(**kwargs):
        updates.append(kwargs)
        raise ValueError("shared task changed since you opened it")

    monkeypatch.setattr(tasks_render.task_db, "update_shared_task", stale)

    tasks_render._save_callback(Path("/tmp/tasks"))

    assert len(updates) == 1
    assert fake_st.session_state[tasks_render.K_SAVE_ERROR] == (
        "shared task changed since you opened it"
    )
    assert fake_st.session_state[tasks_render.K_EDITOR_OPEN] is True
    assert materialized == []
    assert reloads == []


def test_non_admin_cannot_save_collaborative_code_after_state_tampering(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    row = _code_row(owner="owner@example.edu", visibility="shared")
    _save_state(tasks_render, row, actor="editor@example.edu", mode="code")
    updates, *_ = _wire_save(
        monkeypatch, tasks_render, actor="editor@example.edu", is_admin=False
    )

    tasks_render._save_callback(Path("/tmp/tasks"))

    assert updates == []
    assert fake_st.session_state[tasks_render.K_SAVE_ERROR] == (
        "Only an administrator can edit a shared code task."
    )
    assert fake_st.session_state[tasks_render.K_EDITOR_OPEN] is True


def test_admin_can_save_collaborative_code_with_owner_audit(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    row = _code_row(owner="owner@example.edu", visibility="shared")
    _save_state(tasks_render, row, actor="admin@example.edu", mode="code")
    updates, owner_saves, deletes, _materialized, _reloads, audits = _wire_save(
        monkeypatch, tasks_render, actor="admin@example.edu", is_admin=True
    )

    tasks_render._save_callback(Path("/tmp/tasks"))

    assert len(updates) == 1
    assert owner_saves == []
    assert deletes == []
    assert audits[-1][0] == ("admin-action",)
    assert audits[-1][1]["task_owner"] == "owner@example.edu"


def test_owner_save_retains_rename_behavior(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    row = _form_row(owner="owner@example.edu", visibility="private")
    _save_state(tasks_render, row, actor="owner@example.edu")
    fake_st.session_state[tasks_render.K_EDITOR_NAME_INPUT] = "renamed-cleanup"
    updates, owner_saves, deletes, _materialized, _reloads, audits = _wire_save(
        monkeypatch, tasks_render, actor="owner@example.edu", is_admin=False
    )

    tasks_render._save_callback(Path("/tmp/tasks"))

    assert updates == []
    assert deletes == [("owner@example.edu", "cleanup")]
    assert owner_saves[0]["owner"] == "owner@example.edu"
    assert owner_saves[0]["name"] == "renamed-cleanup"
    assert owner_saves[0]["visibility"] == "private"
    assert audits[-1][1]["collaborative_edit"] is False


def test_collaborative_editor_disables_owner_controlled_fields(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    row = _form_row(owner="owner@example.edu", visibility="shared")
    _save_state(tasks_render, row, actor="editor@example.edu")
    monkeypatch.setattr(tasks_render, "_render_form_editor", lambda: None)
    monkeypatch.setattr(
        tasks_render, "_ai_draft_save_blocked_for_new_task", lambda: False
    )

    tasks_render._render_editor(Path("/tmp/tasks"), is_admin=False)

    name_input = next(
        kwargs
        for label, kwargs in fake_st.text_inputs
        if label.startswith("Task name")
    )
    description_input = next(
        kwargs
        for label, kwargs in fake_st.text_inputs
        if label.startswith("Description")
    )
    visibility = next(
        kwargs for label, kwargs in fake_st.radios if label == "Visibility"
    )
    assert name_input["disabled"] is True
    assert description_input.get("disabled", False) is False
    assert visibility["disabled"] is True
    assert any("owner retains" in caption for caption in fake_st.captions)
