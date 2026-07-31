"""Tests for compact task operation cards."""

from contextlib import nullcontext
import copy

import pytest

from marcedit_web.lib import guided_replace_preview
from marcedit_web.render import task_operation_cards


class Store:
    def __init__(self, revision=4):
        self.revision = revision


STORE = Store()


def guided_operation(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "contains",
        "find": "TFeba",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "(SCTFEBA)",
        "occurrences": "all",
        "value_scope": "all",
        "condition": "always",
    }
    params.update(changes)
    return {"kind": "guided-find-replace", "params": params}


def current_preview_for(operation, *, store=STORE, error=None):
    return guided_replace_preview.GuidedReplacePreview(
        request=copy.deepcopy(operation["params"]),
        store_id=id(store),
        store_revision=store.revision,
        error=error,
    )


def add_operation():
    return {
        "kind": "add-field",
        "params": {
            "tag": "650",
            "ind1": " ",
            "ind2": "0",
            "subfields": [["a", "Libraries"]],
            "condition": "always",
            "existing_field_action": "append",
        },
    }


def build_operation():
    return {
        "kind": "build-field",
        "params": {
            "tag": "035",
            "ind1": " ",
            "ind2": " ",
            "structured_subfields": [[
                "a",
                [
                    {"type": "text", "value": "("},
                    {"type": "control_field", "tag": "003"},
                    {"type": "text", "value": ")"},
                    {"type": "control_field", "tag": "001"},
                ],
            ]],
            "condition": "always",
            "existing_field_action": "append",
            "missing_control_action": "skip_field",
        },
    }


def op(kind):
    return {"kind": kind, "params": {}}


def test_add_build_and_generic_cards_use_cataloger_facing_descriptions():
    add_view = task_operation_cards.operation_card_view(
        add_operation(), position=1, store=None, previews={}
    )
    build_view = task_operation_cards.operation_card_view(
        build_operation(), position=2, store=None, previews={}
    )
    generic_view = task_operation_cards.operation_card_view(
        {"kind": "delete-tag", "params": {"tag": "999"}},
        position=3,
        store=None,
        previews={},
    )

    assert add_view.label == "Add field"
    assert "subfield a containing “Libraries”" in add_view.summary
    assert add_view.target == "650"
    assert add_view.preview_status == ""
    assert build_view.label == "Build field from template"
    assert "built from 003 and 001" in build_view.summary
    assert build_view.target == "035"
    assert generic_view.summary == "Remove every field with this tag."
    assert generic_view.validation_status == "Valid"


def test_guided_card_uses_plain_summary_target_and_request_keyed_preview():
    operation = guided_operation(tag="035", subfield="a")
    preview = current_preview_for(operation)

    view = task_operation_cards.operation_card_view(
        operation,
        position=2,
        store=STORE,
        previews={
            guided_replace_preview.preview_cache_key(operation): preview
        },
    )

    assert view.position == 2
    assert view.label == "Guided find and replace"
    assert view.target == "035 $a"
    assert view.validation_status == "Valid"
    assert view.preview_status == "Current"
    assert "Keep text before and after" in view.summary


def test_unknown_and_unresolved_cards_preserve_technical_identity():
    unknown = {"kind": "future-operation", "params": {"opaque": 1}}
    unresolved = {
        "kind": "build-field",
        "params": {"subfields": [["a", "literal {name}"]]},
        "authoring_error": "source line needs review",
    }

    unknown_view = task_operation_cards.operation_card_view(
        unknown, position=1, store=None, previews={}
    )
    unresolved_view = task_operation_cards.operation_card_view(
        unresolved, position=2, store=None, previews={}
    )

    assert unknown_view.validation_status == "Needs attention"
    assert unknown_view.kind == "future-operation"
    assert unknown_view.summary == (
        "Unsupported operation; technical values are preserved."
    )
    assert unresolved_view.validation_errors == (
        "source line needs review",
    )


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("no-cache", "Not previewed"),
        ("changed-request", "Not previewed"),
        ("current", "Current"),
        ("stale", "Stale"),
        ("failed", "Failed"),
    ],
)
def test_guided_preview_status_is_request_keyed(case, expected):
    operation = guided_operation()
    store = Store()
    previews = {}
    if case == "changed-request":
        other = guided_operation(replacement="other")
        previews[guided_replace_preview.preview_cache_key(other)] = (
            current_preview_for(other, store=store)
        )
    elif case != "no-cache":
        preview = current_preview_for(
            operation,
            store=store,
            error="preview failed" if case == "failed" else None,
        )
        if case == "stale":
            preview = guided_replace_preview.GuidedReplacePreview(
                request=preview.request,
                store_id=preview.store_id,
                store_revision=store.revision - 1,
            )
        previews[guided_replace_preview.preview_cache_key(operation)] = preview

    view = task_operation_cards.operation_card_view(
        operation, position=1, store=store, previews=previews
    )

    assert view.preview_status == expected


def test_invalid_guided_request_reports_attention_without_preview_crash():
    view = task_operation_cards.operation_card_view(
        guided_operation(tag=""), position=1, store=STORE, previews={}
    )

    assert view.validation_status == "Needs attention"
    assert view.preview_status == "Not previewed"


def test_operation_card_view_is_immutable():
    view = task_operation_cards.operation_card_view(
        add_operation(), position=1, store=None, previews={}
    )

    with pytest.raises(AttributeError):
        view.summary = "changed"


def test_reorder_and_remove_copy_the_list_without_rewriting_operations():
    operations = [op("a"), op("b"), op("c")]

    moved = task_operation_cards.move_operation(operations, 1, -1)
    removed = task_operation_cards.remove_operation(operations, 1)

    assert [item["kind"] for item in moved] == ["b", "a", "c"]
    assert [item["kind"] for item in removed] == ["a", "c"]
    assert [item["kind"] for item in operations] == ["a", "b", "c"]
    assert moved is not operations
    assert moved[0] is operations[1]
    assert removed[0] is operations[0]


class FakeColumn:
    def __init__(self, streamlit):
        self.streamlit = streamlit

    def markdown(self, value):
        self.streamlit.markdowns.append(value)

    def caption(self, value):
        self.streamlit.captions.append(value)

    def button(self, label, **kwargs):
        return self.streamlit.button(label, **kwargs)


class FakeStreamlit:
    def __init__(self, clicked=()):
        self.clicked = set(clicked)
        self.session_state = {}
        self.containers = []
        self.markdowns = []
        self.captions = []
        self.buttons = []

    def container(self, **kwargs):
        self.containers.append(kwargs)
        return nullcontext()

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [FakeColumn(self) for _ in range(count)]

    def markdown(self, value):
        self.markdowns.append(value)

    def caption(self, value):
        self.captions.append(value)

    def button(self, label, **kwargs):
        call = {"label": label, **kwargs}
        self.buttons.append(call)
        return kwargs.get("key") in self.clicked


def _render(monkeypatch, fake, operations, changes, edits):
    monkeypatch.setattr(task_operation_cards, "st", fake)
    task_operation_cards.render_operation_cards(
        operations,
        store=None,
        previews={},
        on_edit=edits.append,
        on_change=changes.append,
        key_prefix="cards",
    )


def test_cards_render_compact_status_and_accessible_actions(monkeypatch):
    fake = FakeStreamlit(clicked={"cards_0_edit"})
    edits = []

    _render(monkeypatch, fake, [add_operation()], [], edits)

    assert fake.containers == [{"border": True}]
    assert any("1. Add field" in value for value in fake.markdowns)
    assert any("Valid" in value for value in fake.captions)
    assert edits == [0]
    assert any(call["label"] == "Edit" for call in fake.buttons)
    assert {
        call["help"]
        for call in fake.buttons
        if call["label"] in {"↑", "↓"}
    } == {"Move operation up", "Move operation down"}


def test_card_renders_one_concise_error_but_collapses_multiple_errors(
    monkeypatch,
):
    concise = FakeStreamlit()
    _render(
        monkeypatch,
        concise,
        [{
            "kind": "build-field",
            "params": {},
            "authoring_error": "source line needs review",
        }],
        [],
        [],
    )
    assert "Needs attention — source line needs review" in concise.captions

    multiple = FakeStreamlit()
    _render(
        monkeypatch,
        multiple,
        [{"kind": "add-field", "params": {}}],
        [],
        [],
    )
    assert any(
        "Needs attention — edit to review" in value
        for value in multiple.captions
    )
    assert all("tag must be" not in value for value in multiple.captions)


def test_remove_requires_a_second_confirm_click(monkeypatch):
    operations = [add_operation(), build_operation()]
    changes = []
    fake = FakeStreamlit(clicked={"cards_0_remove"})

    _render(monkeypatch, fake, operations, changes, [])

    assert changes == []
    assert fake.session_state == {"cards_pending_remove": 0}

    fake.clicked = {"cards_0_confirm_remove"}
    _render(monkeypatch, fake, operations, changes, [])

    assert len(changes) == 1
    assert changes[0] == [operations[1]]
    assert changes[0] is not operations
    assert "cards_pending_remove" not in fake.session_state


def test_reorder_calls_on_change_with_a_copied_list(monkeypatch):
    operations = [add_operation(), build_operation()]
    changes = []
    fake = FakeStreamlit(clicked={"cards_1_up"})

    _render(monkeypatch, fake, operations, changes, [])

    assert changes == [[operations[1], operations[0]]]
    assert changes[0] is not operations
