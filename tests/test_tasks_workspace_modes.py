"""Tasks page mode switcher (TASK-143).

The page previously stacked authoring, running, results, history, and
quick tools in one scroll. These tests pin the new contract: exactly
one mode renders per run, the selection survives reruns via
session_state, and opening the editor forces Build & import so the
editor is never rendered invisibly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.radios: list[dict] = []
        self.dividers = 0
        self.warnings = []
        self.errors = []
        self.successes = []
        self.code_blocks = []

    def radio(self, label, options, horizontal=False, key=None,
              label_visibility=None):
        self.radios.append(
            {"label": label, "options": tuple(options), "key": key}
        )
        value = self.session_state.get(key)
        if value is None:
            value = options[0]
            self.session_state[key] = value
        return value

    def divider(self):
        self.dividers += 1

    def container(self):
        return self

    def expander(self, label):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def caption(self, value):
        return None

    def warning(self, value):
        self.warnings.append(str(value))

    def markdown(self, value):
        return None

    def error(self, value):
        self.errors.append(str(value))

    def success(self, value):
        self.successes.append(str(value))

    def code(self, value, **kwargs):
        self.code_blocks.append(str(value))

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]

    def button(self, label, **kwargs):
        return False

    def selectbox(self, label, options, **kwargs):
        return options[0]


def _tasks_render(monkeypatch, fake_st):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    monkeypatch.setattr(tasks_render, "st", fake_st)
    return tasks_render


def _wire(monkeypatch, tasks_render, calls):
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.task_admin, "is_admin", lambda user: False
    )
    monkeypatch.setattr(
        tasks_render, "_refresh_tasks_for", lambda user: Path("/tmp/tasks")
    )
    monkeypatch.setattr(
        tasks_render.tasks,
        "load_user_tasks",
        lambda d, force_reload=False: None,
    )
    monkeypatch.setattr(tasks_render.tasks, "all_tasks", lambda: {})
    monkeypatch.setattr(tasks_render, "loaded_batch_status", lambda: None)
    monkeypatch.setattr(
        tasks_render, "_render_run_mode",
        lambda registered, tasks_dir: calls.append("run"),
    )
    monkeypatch.setattr(
        tasks_render, "_render_quick_ops_mode",
        lambda: calls.append("quick"),
    )
    monkeypatch.setattr(
        tasks_render, "_render_build_mode",
        lambda *args: calls.append("build"),
    )


def test_default_mode_is_run_and_only_run(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)

    tasks_render.render()

    assert calls == ["run"]
    assert fake_st.session_state[tasks_render.K_MODE_WIDGET] == (
        tasks_render.MODE_RUN
    )


def test_mode_selection_survives_rerun(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)
    fake_st.session_state[tasks_render.K_MODE_WIDGET] = (
        tasks_render.MODE_QUICK
    )

    tasks_render.render()

    assert calls == ["quick"]


def test_force_mode_overrides_and_clears(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    calls: list[str] = []
    _wire(monkeypatch, tasks_render, calls)
    fake_st.session_state[tasks_render.K_MODE_WIDGET] = (
        tasks_render.MODE_RUN
    )
    fake_st.session_state[tasks_render.K_FORCE_MODE] = (
        tasks_render.MODE_BUILD
    )

    tasks_render.render()

    assert calls == ["build"]
    assert tasks_render.K_FORCE_MODE not in fake_st.session_state
    assert fake_st.session_state[tasks_render.K_MODE_WIDGET] == (
        tasks_render.MODE_BUILD
    )


def test_open_editor_for_new_forces_build_mode(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)

    tasks_render._open_editor_for_new()

    assert fake_st.session_state[tasks_render.K_FORCE_MODE] == (
        tasks_render.MODE_BUILD
    )


def test_new_build_field_defaults_are_structured(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)

    params = tasks_render._default_params_for("build-field")

    assert "subfields" not in params
    assert "if_absent" not in params
    assert params["structured_subfields"] == []
    assert params["existing_field_action"] == "append"
    assert params["missing_control_action"] == "skip_field"


def test_existing_legacy_build_is_normalized_in_memory(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    rendered = tasks_render.task_builder.render_ops_to_python(
        [
            tasks_render.Operation(
                kind="build-field",
                params={
                    "tag": "876",
                    "ind1": " ",
                    "ind2": " ",
                    "subfields": [["a", "B({003}){001}-SC"]],
                    "condition": "always",
                    "if_absent": False,
                },
            )
        ]
    )

    tasks_render._open_editor_for_existing_row(
        {
            "name": "legacy-build",
            "description": "",
            "body": rendered["body"],
            "visibility": "private",
        },
        is_admin=False,
    )

    params = fake_st.session_state[tasks_render.K_EDITOR_OPS][0]["params"]
    assert "subfields" not in params
    assert "if_absent" not in params
    assert params["existing_field_action"] == "append"
    assert params["structured_subfields"][0][1][1] == {
        "type": "control_field",
        "tag": "003",
    }


def test_unconvertible_legacy_build_remains_visible_in_memory(monkeypatch):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    body = (
        '# OP: build-field {"tag":"876","ind1":" ","ind2":" ",'
        '"subfields":[["a","literal {name}"]],"if_absent":false}\n'
        "pass"
    )

    tasks_render._open_editor_for_existing_row(
        {
            "name": "legacy-braces",
            "description": "",
            "body": body,
            "visibility": "private",
        },
        is_admin=False,
    )

    operation = fake_st.session_state[tasks_render.K_EDITOR_OPS][0]
    assert operation["params"]["subfields"] == [["a", "literal {name}"]]
    assert "cannot convert" in operation["authoring_error"]


def test_invalid_persisted_condition_remains_visible_without_form_coercion(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    body = (
        '# OP: add-field {"tag":"877","ind1":" ","ind2":" ",'
        '"subfields":[["m","Map"]],"condition":"future-condition"}\n'
        "pass"
    )

    tasks_render._open_editor_for_existing_row(
        {
            "name": "future-condition",
            "description": "",
            "body": body,
            "visibility": "private",
        },
        is_admin=False,
    )

    operation = fake_st.session_state[tasks_render.K_EDITOR_OPS][0]
    assert operation["params"]["condition"] == "future-condition"
    assert "record condition" in operation["authoring_error"]


def test_form_editor_fetches_preview_record_once_and_delegates_add_build(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state[tasks_render.K_EDITOR_OPS] = [
        {
            "kind": "add-field",
            "params": {
                "tag": "877",
                "subfields": [["m", "Map"]],
                "existing_field_action": "append",
            },
        },
        {
            "kind": "build-field",
            "params": {
                "tag": "876",
                "structured_subfields": [
                    ["a", [{"type": "text", "value": "Internet"}]]
                ],
                "existing_field_action": "append",
                "missing_control_action": "skip_field",
            },
        },
    ]
    calls = []

    class Store:
        def __init__(self):
            self.get_calls = []

        def count(self):
            return 1

        def get(self, index):
            self.get_calls.append(index)
            return "first-record"

    store = Store()
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(tasks_render.task_admin, "is_admin", lambda user: False)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    monkeypatch.setattr(
        tasks_render.task_authoring_render,
        "render_add_field_params",
        lambda params, key_prefix: calls.append(("add", key_prefix)),
    )
    monkeypatch.setattr(
        tasks_render.task_authoring_render,
        "render_build_field_params",
        lambda params, key_prefix: calls.append(("build", key_prefix)),
    )
    monkeypatch.setattr(
        tasks_render.task_authoring_render,
        "render_operation_explanation",
        lambda op, record: calls.append(("preview", record)),
    )

    tasks_render._render_form_editor()

    assert store.get_calls == [0]
    assert ("add", "op_0") in calls
    assert ("build", "op_1") in calls
    assert calls.count(("preview", "first-record")) == 2


def _wire_successful_save(monkeypatch, tasks_render, saved):
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render, "_ai_draft_save_blocked_for_new_task", lambda: False
    )
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )
    monkeypatch.setattr(
        tasks_render.task_db, "materialize_to_dir", lambda *args: None
    )
    monkeypatch.setattr(
        tasks_render.tasks, "load_user_tasks", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        tasks_render.task_admin, "is_admin", lambda user: False
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *args, **kwargs: None)


def _form_save_state(tasks_render, operations):
    return {
        tasks_render.K_EDITOR_NAME_INPUT: "structured-fields",
        tasks_render.K_EDITOR_DESCRIPTION_INPUT: "",
        tasks_render.K_EDITOR_MODE: "form",
        tasks_render.K_EDITOR_VISIBILITY: "private",
        tasks_render.K_EDITOR_OPS: operations,
    }


def test_save_blocks_invalid_structured_field_before_sql(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [
                {
                    "kind": "add-field",
                    "params": {
                        "tag": "877",
                        "ind1": " ",
                        "ind2": " ",
                        "subfields": [],
                        "existing_field_action": "append",
                        "condition": "always",
                    },
                }
            ],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "Operation 1" in fake_st.session_state[tasks_render.K_SAVE_ERROR]
    assert "at least one subfield" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_unconvertible_legacy_build_remains_visible_but_blocks_form_save(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [
                {
                    "kind": "build-field",
                    "authoring_error": (
                        "cannot convert legacy Build Field text losslessly"
                    ),
                    "params": {
                        "tag": "876",
                        "ind1": " ",
                        "ind2": " ",
                        "subfields": [["a", "literal {name}"]],
                    },
                }
            ],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "cannot convert" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]


def test_existing_unresolved_custom_op_can_be_preserved_during_save(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        _form_save_state(
            tasks_render,
            [
                {
                    "kind": "custom",
                    "params": {
                        "code": (
                            "# TODO: buildnewfield template "
                            "'=876  \\\\$a{001}' — recreate with "
                            "structured Build Field"
                        )
                    },
                }
            ],
        )
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert len(saved) == 1


def test_stale_form_errors_do_not_block_code_mode_save(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update(
        {
            tasks_render.K_EDITOR_NAME_INPUT: "code-task",
            tasks_render.K_EDITOR_DESCRIPTION_INPUT: "",
            tasks_render.K_EDITOR_MODE: "code",
            tasks_render.K_EDITOR_VISIBILITY: "private",
            tasks_render.K_EDITOR_BODY: "pass",
            tasks_render.K_EDITOR_OPS: [
                {
                    "kind": "add-field",
                    "params": {"tag": "bad", "subfields": []},
                }
            ],
        }
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)

    tasks_render._save_callback(tmp_path)

    assert len(saved) == 1


def test_new_unresolved_text_import_is_not_persisted(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.quotas, "check_upload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(tasks_render, "audit_event", lambda *args, **kwargs: None)
    saved = []
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )
    upload = SimpleNamespace(
        name="rda.tasksfile",
        getvalue=lambda: b"RDAHELPER\n",
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    assert any("Not imported" in warning for warning in fake_st.warnings)
    assert fake_st.code_blocks == ["RDAHELPER"]


def test_save_callback_reports_invalid_form_regex_without_persisting(
    monkeypatch, tmp_path,
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    fake_st.session_state.update({
        tasks_render.K_EDITOR_NAME_INPUT: "invalid-regex",
        tasks_render.K_EDITOR_DESCRIPTION_INPUT: "Invalid regex task",
        tasks_render.K_EDITOR_MODE: "form",
        tasks_render.K_EDITOR_VISIBILITY: "private",
        tasks_render.K_EDITOR_OPS: [{
            "kind": "replace-field-subfield-and-indicators",
            "params": {
                "tag": "035",
                "match_ind1": " ",
                "match_ind2": " ",
                "match_code": "a",
                "match_value": "(",
                "regex": True,
                "ignore_case": False,
                "new_ind1": " ",
                "new_ind2": "9",
                "new_code": "a",
                "new_value": "replacement",
            },
        }],
    })
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render, "_ai_draft_save_blocked_for_new_task", lambda: False
    )
    saved = []
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )

    tasks_render._save_callback(tmp_path)

    assert saved == []
    assert "invalid match regex" in fake_st.session_state[
        tasks_render.K_SAVE_ERROR
    ]
