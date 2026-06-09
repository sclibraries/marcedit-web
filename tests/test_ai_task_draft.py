"""Tests for validating AI-authored task drafts before editor import."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from marcedit_web.lib.ai_task_draft import (
    DraftValidationError,
    blocking_issue_count,
    operations_for_editor,
    parse_ai_task_draft,
)


def _draft(**overrides) -> str:
    data = {
        "task_name": "routledge-eba",
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
    assert review.rejected_operations[0].reason == "param 'subfields' must be a list"


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


def test_ai_draft_review_helper_preserves_low_confidence_and_rejected_source_text():
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    review = SimpleNamespace(
        task_name="routledge-eba",
        operations=(
            SimpleNamespace(
                kind="replace-field-data-by-regex",
                params={
                    "tag": "245",
                    "pattern": r"\s+/$",
                    "replacement": "",
                },
                confidence="low",
                explanation="Cataloger note says to strip trailing slash.",
            ),
        ),
        rejected_operations=(
            SimpleNamespace(
                kind="vendor-specific-cleanup",
                params={"line": "Normalize package notes"},
                reason="unknown operation kind 'vendor-specific-cleanup'",
                source_text="Normalize package notes",
            ),
        ),
        questions=(),
        manual_notes=(),
        unsupported_lines=(),
    )

    accepted_summary = tasks_render._ai_draft_operation_summary(review.operations[0])
    rejected_summary = tasks_render._ai_draft_rejected_operation_summary(
        review.rejected_operations[0]
    )

    assert "confidence: low" in accepted_summary
    assert "Cataloger note says to strip trailing slash." in accepted_summary
    assert blocking_issue_count(review) == 1
    assert "Normalize package notes" in rejected_summary
