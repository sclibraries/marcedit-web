"""Tests for validating AI-authored task drafts before editor import."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from marcedit_web.lib import task_builder
from marcedit_web.lib.ai_task_draft import (
    DraftValidationError,
    blocking_issue_count,
    operations_for_editor,
    parse_ai_task_draft,
)
from marcedit_web.lib.task_builder import Operation


TASKS_RENDER_SOURCE = Path("marcedit_web/render/tasks.py")


def _draft(**overrides) -> str:
    data = {
        "task_name": "routledge-eba",
        "description": "",
        "operations": [],
        "questions": [],
        "manual_notes": [],
        "unsupported_lines": [],
    }
    data.update(overrides)
    return json.dumps(data)


def test_valid_regex_operation_maps_to_editor_op():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "replace-field-data-by-regex",
                    "params": {
                        "tag": "245",
                        "pattern": r"\s+/$",
                        "replacement": "",
                        "ignore_case": True,
                    },
                }
            ],
        )
    )

    assert review.rejected_operations == ()
    assert operations_for_editor(review) == [
        {
            "kind": "replace-field-data-by-regex",
            "params": {
                "tag": "245",
                "pattern": r"\s+/$",
                "replacement": "",
                "ignore_case": True,
            },
        }
    ]


def test_ai_draft_editor_ops_round_trip_through_task_builder_markers():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "replace-field-data-by-regex",
                    "regex": {
                        "pattern": "^TFeba",
                        "meaning": "vendor prefix at the start of 001",
                        "before": "TFeba12345",
                        "after": "SCTFEBA12345",
                    },
                    "params": {
                        "tag": "001",
                        "pattern": "^TFeba",
                        "replacement": "SCTFEBA",
                        "ignore_case": False,
                    },
                },
                {
                    "kind": "add-field",
                    "params": {
                        "tag": "710",
                        "ind1": "2",
                        "ind2": " ",
                        "subfields": [["a", "Routledge EBA"]],
                        "condition": "always",
                        "if_absent": False,
                    },
                },
            ],
        )
    )
    ops = [Operation.from_dict(op) for op in operations_for_editor(review)]

    rendered = task_builder.render_ops_to_python(ops)
    parsed = task_builder.parse_ops_from_source(rendered["body"])

    assert parsed["form_editable"] is True
    assert [op.kind for op in parsed["ops"]] == [
        "replace-field-data-by-regex",
        "add-field",
    ]
    assert parsed["ops"][0].params["replacement"] == "SCTFEBA"
    assert parsed["ops"][1].params["subfields"] == [["a", "Routledge EBA"]]


def test_markdown_wrapped_json_is_rejected():
    raw = "```json\n" + _draft() + "\n```"

    with pytest.raises(DraftValidationError, match="JSON object"):
        parse_ai_task_draft(raw)


def test_unknown_operation_kind_becomes_rejected_item():
    review = parse_ai_task_draft(
        _draft(operations=[{"kind": "invent-new-op", "params": {"tag": "999"}}])
    )

    assert review.operations == ()
    assert len(review.rejected_operations) == 1
    assert review.rejected_operations[0].kind == "invent-new-op"
    assert "unknown operation kind" in review.rejected_operations[0].reason


def test_unknown_params_are_rejected():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {"kind": "delete-tag", "params": {"tag": "029", "extra": "nope"}}
            ],
        )
    )

    assert review.operations == ()
    assert review.rejected_operations[0].reason == "unknown param 'extra'"


def test_wrong_param_type_is_rejected_with_specific_message():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "add-field",
                    "params": {"tag": "590", "subfields": "a Routledge"},
                }
            ],
        )
    )

    assert review.operations == ()
    assert review.rejected_operations[0].reason == (
        "param 'subfields' must be a list of [code, value] pairs, "
        'e.g. [["a", "Electronic scores."], ["2", "local"]]'
    )


def test_invalid_subfields_shape_explains_expected_pairs():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "add-field",
                    "params": {
                        "tag": "655",
                        "subfields": {"a": "Electronic scores.", "2": "local"},
                    },
                }
            ],
        )
    )

    assert review.operations == ()
    assert review.rejected_operations[0].reason == (
        "param 'subfields' must be a list of [code, value] pairs, "
        'e.g. [["a", "Electronic scores."], ["2", "local"]]'
    )


def test_invalid_select_param_values_are_rejected():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "add-field",
                    "params": {
                        "tag": "590",
                        "subfields": [["a", "Routledge EBA record"]],
                        "condition": "not-a-real-condition",
                    },
                },
                {
                    "kind": "add-subfield",
                    "params": {
                        "tag": "856",
                        "code": "z",
                        "value": "Connect to resource",
                        "position": "middle",
                    },
                },
            ],
        )
    )

    assert review.operations == ()
    assert len(review.rejected_operations) == 2
    assert review.rejected_operations[0].reason.startswith(
        "param 'condition' must be one of:"
    )
    assert review.rejected_operations[1].reason == (
        "param 'position' must be one of: end, start"
    )


def test_invalid_regex_is_rejected():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "delete-856-url-regex",
                    "params": {"pattern": "["},
                }
            ],
        )
    )

    assert review.operations == ()
    assert "invalid regex in param 'pattern'" in review.rejected_operations[0].reason


def test_questions_are_blocking_manual_notes_are_not():
    review = parse_ai_task_draft(
        _draft(
            questions=["Should 856 links with proxy text be deleted?"],
            manual_notes=["Review vendor-specific 590 wording after import."],
        )
    )

    assert review.questions == ("Should 856 links with proxy text be deleted?",)
    assert review.manual_notes == ("Review vendor-specific 590 wording after import.",)
    assert blocking_issue_count(review) == 1


def test_code_shaped_values_are_rejected():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "add-subfield",
                    "params": {
                        "tag": "856",
                        "code": "z",
                        "value": "__import__('os').system('whoami')",
                    },
                }
            ],
        )
    )

    assert review.operations == ()
    assert "code-shaped value" in review.rejected_operations[0].reason


def test_record_method_values_are_rejected_as_code_shaped():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "add-subfield",
                    "params": {
                        "tag": "856",
                        "code": "z",
                        "value": "record.remove_fields('029')",
                    },
                }
            ],
        )
    )

    assert review.operations == ()
    assert "code-shaped value" in review.rejected_operations[0].reason


def test_normal_text_containing_record_dot_com_is_allowed():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "add-subfield",
                    "params": {
                        "tag": "856",
                        "code": "z",
                        "value": "Connect through record.com for access",
                    },
                }
            ],
        )
    )

    assert review.rejected_operations == ()
    assert operations_for_editor(review) == [
        {
            "kind": "add-subfield",
            "params": {
                "tag": "856",
                "code": "z",
                "value": "Connect through record.com for access",
            },
        }
    ]


def test_custom_operation_with_python_code_is_rejected():
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "custom",
                    "params": {"code": "record.remove_fields('029')"},
                }
            ],
        )
    )

    assert review.operations == ()
    assert review.rejected_operations[0].kind == "custom"
    assert review.rejected_operations[0].reason == (
        "custom operations are not supported in AI drafts"
    )


def test_routledge_style_fixture_accepts_common_ops_and_preserves_review_items():
    review = parse_ai_task_draft(
        _draft(
            task_name="routledge-eba-cleanup",
            operations=[
                {"kind": "delete-tag", "params": {"tag": "029"}},
                {
                    "kind": "delete-856-url-contains",
                    "params": {"match": "routledge.com/books"},
                },
                {
                    "kind": "add-field",
                    "params": {
                        "tag": "590",
                        "ind1": " ",
                        "ind2": " ",
                        "subfields": [["a", "Routledge EBA record"]],
                        "condition": "always",
                        "if_absent": True,
                    },
                },
                {
                    "kind": "subfield-replace",
                    "params": {
                        "tag": "856",
                        "code": "z",
                        "find": r"^Click here.*",
                        "replace": "Connect to resource",
                        "regex": True,
                        "ignore_case": True,
                    },
                },
                {
                    "kind": "vendor-specific-cleanup",
                    "params": {"line": "Normalize Routledge package note"},
                },
            ],
            questions=["Confirm whether 490 series cleanup is in scope."],
            manual_notes=["Cataloger asked to preserve local 590 notes."],
            unsupported_lines=["Normalize Routledge package note"],
        )
    )

    assert [op.kind for op in review.operations] == [
        "delete-tag",
        "delete-856-url-contains",
        "add-field",
        "subfield-replace",
    ]
    assert len(review.rejected_operations) == 1
    assert review.questions == ("Confirm whether 490 series cleanup is in scope.",)
    assert review.manual_notes == ("Cataloger asked to preserve local 590 notes.",)
    assert review.unsupported_lines == ("Normalize Routledge package note",)
    assert operations_for_editor(review)[2] == {
        "kind": "add-field",
        "params": {
            "tag": "590",
            "ind1": " ",
            "ind2": " ",
            "subfields": [["a", "Routledge EBA record"]],
            "condition": "always",
            "if_absent": True,
        },
    }


def test_ai_draft_parser_preserves_review_metadata_for_handoff():
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    review = parse_ai_task_draft(
        _draft(
            description="Remove vendor cleanup fields for Routledge EBA.",
            operations=[
                {
                    "kind": "replace-field-data-by-regex",
                    "source_text": "Strip trailing slash from 245.",
                    "explanation": "Cataloger note says to strip trailing slash.",
                    "confidence": "low",
                    "regex": {
                        "pattern": r"\s+/$",
                        "meaning": "trailing slash after whitespace",
                        "before": "Title /",
                        "after": "Title",
                    },
                    "params": {
                        "tag": "245",
                        "pattern": r"\s+/$",
                        "replacement": "",
                    },
                },
                {
                    "kind": "vendor-specific-cleanup",
                    "source_text": "Normalize package notes",
                    "params": {"line": "Normalize package notes"},
                },
            ],
        )
    )

    assert review.description == "Remove vendor cleanup fields for Routledge EBA."
    assert review.operations[0].source_text == "Strip trailing slash from 245."
    assert review.operations[0].confidence == "low"
    assert review.operations[0].explanation == (
        "Cataloger note says to strip trailing slash."
    )
    assert review.operations[0].regex == {
        "pattern": r"\s+/$",
        "meaning": "trailing slash after whitespace",
        "before": "Title /",
        "after": "Title",
    }
    assert review.rejected_operations[0].source_text == "Normalize package notes"

    accepted_summary = tasks_render._ai_draft_operation_summary(review.operations[0])
    rejected_summary = tasks_render._ai_draft_rejected_operation_summary(
        review.rejected_operations[0]
    )

    assert "confidence: low" in accepted_summary
    assert "Cataloger note says to strip trailing slash." in accepted_summary
    assert "meaning: trailing slash after whitespace" in accepted_summary
    assert blocking_issue_count(review) == 1
    assert "Normalize package notes" in rejected_summary


def test_task_draft_ui_does_not_use_ai_draft_wording():
    source = TASKS_RENDER_SOURCE.read_text()

    assert '"AI draft review"' not in source
    assert '"Clear AI draft"' not in source
    assert "AI draft issue(s)" not in source
    assert "blocking AI draft review items" not in source


def test_ai_draft_save_block_only_applies_to_ai_handoff_editor(monkeypatch):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    state: dict[str, object] = {}
    monkeypatch.setattr(tasks_render.st, "session_state", state)
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "vendor-specific-cleanup",
                    "source_text": "Normalize package notes",
                    "params": {"line": "Normalize package notes"},
                },
            ],
        )
    )
    state[tasks_render.K_AI_DRAFT_REVIEW] = review

    tasks_render._open_editor_for_new()

    assert state[tasks_render.K_EDITOR_FROM_AI_DRAFT] is False
    assert tasks_render._ai_draft_save_blocked_for_new_task() is False

    tasks_render._open_editor_for_ai_draft(review)

    assert state[tasks_render.K_EDITOR_FROM_AI_DRAFT] is True
    assert tasks_render._ai_draft_save_blocked_for_new_task() is True


def test_editor_open_helpers_reset_widget_name_and_description(monkeypatch):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    state: dict[str, object] = {}
    monkeypatch.setattr(tasks_render.st, "session_state", state)
    review = parse_ai_task_draft(
        _draft(
            task_name="ai-draft-task",
            description="AI draft description.",
            operations=[],
        )
    )

    tasks_render._open_editor_for_ai_draft(review)
    assert state[tasks_render.K_EDITOR_NAME_INPUT] == "ai-draft-task"
    assert state[tasks_render.K_EDITOR_DESCRIPTION_INPUT] == "AI draft description."

    tasks_render._open_editor_for_new()
    assert state[tasks_render.K_EDITOR_NAME_INPUT] == ""
    assert state[tasks_render.K_EDITOR_DESCRIPTION_INPUT] == ""

    tasks_render._open_editor_for_existing_row(
        {
            "name": "existing-task",
            "description": "Existing description.",
            "body": "pass\n",
            "visibility": "private",
        },
        is_admin=False,
    )
    assert state[tasks_render.K_EDITOR_NAME_INPUT] == "existing-task"
    assert state[tasks_render.K_EDITOR_DESCRIPTION_INPUT] == "Existing description."


def test_clearing_ai_draft_closes_ai_handoff_editor(monkeypatch):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    state: dict[str, object] = {}
    monkeypatch.setattr(tasks_render.st, "session_state", state)
    review = parse_ai_task_draft(
        _draft(
            operations=[
                {
                    "kind": "vendor-specific-cleanup",
                    "source_text": "Normalize package notes",
                    "params": {"line": "Normalize package notes"},
                },
            ],
        )
    )
    state[tasks_render.K_AI_DRAFT_REVIEW] = review
    state[tasks_render.K_AI_DRAFT_BLOCKING_ACK] = False
    state[tasks_render.K_AI_DRAFT_ERROR] = "previous error"

    tasks_render._open_editor_for_ai_draft(review)
    tasks_render._clear_ai_draft_review()

    assert state[tasks_render.K_AI_DRAFT_REVIEW] is None
    assert state[tasks_render.K_AI_DRAFT_BLOCKING_ACK] is False
    assert state[tasks_render.K_AI_DRAFT_ERROR] is None
    assert state[tasks_render.K_EDITOR_OPEN] is False
    assert state[tasks_render.K_EDITOR_FROM_AI_DRAFT] is False
    assert state[tasks_render.K_EDITOR_AI_DRAFT_REVIEW] is None


def test_ai_draft_handoff_is_disabled_without_accepted_operations():
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    empty_review = parse_ai_task_draft(_draft(operations=[]))
    accepted_review = parse_ai_task_draft(
        _draft(operations=[{"kind": "delete-tag", "params": {"tag": "029"}}])
    )

    assert tasks_render._ai_draft_handoff_disabled(empty_review) is True
    assert tasks_render._ai_draft_handoff_disabled(accepted_review) is False


def test_ai_handoff_save_block_uses_editor_bound_review(monkeypatch):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    state: dict[str, object] = {}
    monkeypatch.setattr(tasks_render.st, "session_state", state)
    blocked_review = parse_ai_task_draft(
        _draft(
            operations=[
                {"kind": "delete-tag", "params": {"tag": "029"}},
            ],
            questions=["Confirm whether 035 should be added or edited."],
        )
    )
    clean_review = parse_ai_task_draft(
        _draft(
            task_name="clean-draft",
            operations=[
                {"kind": "delete-tag", "params": {"tag": "891"}},
            ],
        )
    )

    state[tasks_render.K_AI_DRAFT_REVIEW] = blocked_review
    tasks_render._open_editor_for_ai_draft(blocked_review)
    state[tasks_render.K_AI_DRAFT_REVIEW] = clean_review

    assert tasks_render._ai_draft_save_blocked_for_new_task() is True


def test_ai_draft_error_clears_stale_review(monkeypatch):
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    state: dict[str, object] = {}
    monkeypatch.setattr(tasks_render.st, "session_state", state)
    stale_review = parse_ai_task_draft(
        _draft(
            operations=[
                {"kind": "delete-tag", "params": {"tag": "029"}},
            ],
        )
    )
    state[tasks_render.K_AI_DRAFT_REVIEW] = stale_review
    state[tasks_render.K_AI_DRAFT_BLOCKING_ACK] = True

    tasks_render._store_ai_draft_error("Gemini request failed")

    assert state[tasks_render.K_AI_DRAFT_ERROR] == "Gemini request failed"
    assert state[tasks_render.K_AI_DRAFT_REVIEW] is None
    assert state[tasks_render.K_AI_DRAFT_BLOCKING_ACK] is False
