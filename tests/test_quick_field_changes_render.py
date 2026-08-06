"""Focused contract tests for the Common field changes renderer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from marcedit_web.lib.quick_field_changes import QuickFieldChangeRequest
from marcedit_web.lib.quick_field_change_runner import QuickFieldChangePreview
from marcedit_web.lib.quick_field_selector import FieldFilter, FieldSelector, Occurrence
from marcedit_web.lib.task_diff import PerRecordDiff, TaskDiffSummary
from marcedit_web.render import quick_field_changes as renderer


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeStreamlit:
    def __init__(self, *, selections=None, pressed=(), session_state=None):
        self.selections = selections or {}
        self.pressed = set(pressed)
        self.session_state = dict(session_state or {})
        self.widgets = []
        self.expanders = []
        self.warnings = []
        self.errors = []
        self.infos = []
        self.metrics = []
        self.captions = []

    def button(self, label, *, key, **kwargs):
        self.widgets.append(("button", label, key, kwargs))
        if kwargs.get("disabled"):
            return False
        return key in self.pressed or label in self.pressed

    def selectbox(self, label, *, options, index=0, key, **kwargs):
        self.widgets.append(("selectbox", label, list(options), key))
        return self.selections.get(label, options[index])

    def text_input(self, label, *, value="", key, **kwargs):
        self.widgets.append(("text_input", label, key, kwargs))
        return self.selections.get(label, value)

    def number_input(self, label, *, value, key, **kwargs):
        self.widgets.append(("number_input", label, key))
        return self.selections.get(label, value)

    def checkbox(self, label, *, value=False, key, **kwargs):
        self.widgets.append(("checkbox", label, key))
        return self.selections.get(label, value)

    def expander(self, label, *, expanded=False, **kwargs):
        self.expanders.append((label, expanded))
        return _Context()

    def warning(self, value):
        self.warnings.append(str(value))

    def error(self, value):
        self.errors.append(str(value))

    def info(self, value):
        self.infos.append(str(value))

    def caption(self, value):
        self.captions.append(str(value))

    def markdown(self, *_args, **_kwargs):
        return None

    def columns(self, count):
        if not isinstance(count, int):
            count = len(count)
        return [SimpleNamespace(metric=lambda label, value: self.metrics.append((label, value))) for _ in range(count)]

    def code(self, *_args, **_kwargs):
        return None


EXPECTED_LABELS = [
    "Add field",
    "Add subfield",
    "Copy field",
    "Delete field",
    "Delete subfield",
    "Move or retag field",
    "Remove exact duplicate fields",
    "Set indicators",
    "Swap field occurrences",
]


def _render(monkeypatch, fake, *, store=object(), on_apply=None):
    monkeypatch.setattr(renderer, "st", fake)
    renderer.render_common_field_changes(
        store,
        job_file_id=None,
        job_file_version_id=None,
        on_apply=on_apply or (lambda *_args: None),
    )


def test_operation_labels_are_alphabetical(monkeypatch):
    fake = FakeStreamlit()
    _render(monkeypatch, fake)
    operation = next(row for row in fake.widgets if row[0] == "selectbox" and row[1] == "Operation")
    assert operation[2] == EXPECTED_LABELS


@pytest.mark.parametrize(
    "label",
    ["Add field", "Remove exact duplicate fields"],
)
def test_collection_operations_omit_occurrence(monkeypatch, label):
    fake = FakeStreamlit(selections={"Operation": label})
    _render(monkeypatch, fake)
    assert not any(row[1] == "Occurrence" for row in fake.widgets)


def test_swap_has_no_every_choice_and_regex_starts_collapsed(monkeypatch):
    fake = FakeStreamlit(selections={"Operation": "Swap field occurrences"})
    _render(monkeypatch, fake)
    occurrence_rows = [row for row in fake.widgets if row[0] == "selectbox" and row[1] == "Occurrence"]
    assert occurrence_rows
    assert all("Every matching field" not in row[2] for row in occurrence_rows)
    assert fake.expanders == []  # no subfield code was entered


def test_control_tag_hides_selector_indicator_and_subfield_controls(monkeypatch):
    fake = FakeStreamlit(
        selections={"Operation": "Delete field", "Field tag": "001"}
    )
    _render(monkeypatch, fake)
    labels = [row[1] for row in fake.widgets]
    assert "Indicator 1 filter" not in labels
    assert "Indicator 2 filter" not in labels
    assert "Subfield code" not in labels


def test_set_indicators_distinguishes_unchanged_and_marc_blank(monkeypatch):
    fake = FakeStreamlit(selections={"Operation": "Set indicators"})
    _render(monkeypatch, fake)
    choices = [row[2] for row in fake.widgets if row[0] == "selectbox" and row[1].startswith("Set indicator")]
    assert choices
    assert choices[0][:2] == ["Leave unchanged", "MARC blank"]


def test_every_match_warns_about_multi_field_change(monkeypatch):
    fake = FakeStreamlit(
        selections={
            "Operation": "Delete field",
            "Occurrence": "Every matching field",
        }
    )
    _render(monkeypatch, fake)
    assert any("multi-field" in warning for warning in fake.warnings)


def test_reset_cleans_preview_artifact_and_prefixed_state(monkeypatch, tmp_path):
    workdir = tmp_path / "preview"
    workdir.mkdir()
    preview = SimpleNamespace(workdir=workdir)
    fake = FakeStreamlit(
        pressed={renderer.K_RESET},
        session_state={renderer.K_PREVIEW: preview, "quick_field_change_widget": "x", "other": 1},
    )
    cleaned = []
    monkeypatch.setattr(renderer.quick_field_change_runner, "cleanup_artifact", cleaned.append)
    _render(monkeypatch, fake)
    assert cleaned == [preview]
    assert not any(key.startswith(renderer.KEY_PREFIX) for key in fake.session_state)
    assert fake.session_state["other"] == 1


def test_changed_request_marks_preview_stale_and_apply_does_not_fire(monkeypatch):
    request = QuickFieldChangeRequest(kind="delete-field")
    preview = QuickFieldChangePreview(
        request=request,
        request_json="not-used",
        store_id=id(object()),
        store_revision=0,
    )
    calls = []
    fake = FakeStreamlit(
        selections={"Operation": "Add field"},
        session_state={renderer.K_PREVIEW: preview},
        pressed={renderer.K_APPLY_BUTTON},
    )
    _render(monkeypatch, fake, store=SimpleNamespace(revision=0), on_apply=lambda *args: calls.append(args))
    assert not calls
    assert any("stale" in message.lower() for message in fake.infos)


def test_preview_error_remains_visible(monkeypatch):
    preview = QuickFieldChangePreview(
        request=QuickFieldChangeRequest(kind="delete-field"),
        request_json="",
        error="sandbox failed",
    )
    fake = FakeStreamlit(
        session_state={renderer.K_PREVIEW: preview},
    )
    _render(monkeypatch, fake, store=None)
    assert fake.errors == ["sandbox failed"]


def test_matrix_order_is_first_last_numbered_every():
    assert renderer.OCCURRENCE_COMPATIBILITY["delete-field"] == (
        "first",
        "last",
        "numbered",
        "every",
    )
    assert renderer.OCCURRENCE_COMPATIBILITY["swap-field-occurrences"] == (
        "first",
        "last",
        "numbered",
    )


@pytest.mark.parametrize("operation", ["Add subfield", "Delete subfield"])
def test_control_tag_hides_operation_subfield_widgets_and_blocks_preview(
    monkeypatch, operation,
):
    fake = FakeStreamlit(
        selections={"Operation": operation, "Field tag": "001"},
        pressed={renderer.K_PREVIEW_BUTTON},
    )
    build_calls = []
    monkeypatch.setattr(
        renderer.quick_field_change_runner,
        "build_preview",
        lambda *args, **kwargs: build_calls.append(args),
    )
    _render(monkeypatch, fake)
    labels = [row[1] for row in fake.widgets]
    assert "Subfield value" not in labels
    assert "Subfield value match" not in labels
    assert not build_calls
    assert any("Control fields cannot" in error for error in fake.errors)


def test_control_tag_set_indicators_blocks_preview(monkeypatch):
    fake = FakeStreamlit(
        selections={"Operation": "Set indicators", "Field tag": "001"},
        pressed={renderer.K_PREVIEW_BUTTON},
    )
    build_calls = []
    monkeypatch.setattr(
        renderer.quick_field_change_runner,
        "build_preview",
        lambda *args, **kwargs: build_calls.append(args),
    )
    _render(monkeypatch, fake)
    assert not build_calls
    assert any("cannot have indicators" in error for error in fake.errors)


@pytest.mark.parametrize("operation", ["Copy field", "Move or retag field"])
def test_copy_and_move_render_destination_controls(monkeypatch, operation):
    fake = FakeStreamlit(selections={"Operation": operation})
    _render(monkeypatch, fake)
    assert any(row[1] == "Destination tag" for row in fake.widgets)


def test_matcher_widgets_pin_existing_character_bound(monkeypatch):
    fake = FakeStreamlit(
        selections={
            "Operation": "Delete field",
            "Field tag": "245",
            "Subfield code": "a",
        }
    )
    _render(monkeypatch, fake)
    match_rows = [row for row in fake.widgets if row[0] == "text_input" and row[1] == "Match value"]
    assert match_rows and match_rows[0][3]["max_chars"] == 1024


def test_raw_regex_changes_filter_mode_without_renderer_compilation(monkeypatch):
    fake = FakeStreamlit(
        selections={
            "Operation": "Delete field",
            "Field tag": "245",
            "Subfield code": "a",
            "Use raw regular expression": True,
        },
        pressed={renderer.K_PREVIEW_BUTTON},
    )
    captured = []
    error_preview = QuickFieldChangePreview(
        request=QuickFieldChangeRequest(kind="delete-field"),
        request_json="",
        error="preview failed",
    )
    monkeypatch.setattr(
        renderer.quick_field_change_runner,
        "build_preview",
        lambda store, request, **kwargs: captured.append(request) or error_preview,
    )
    _render(monkeypatch, fake, store=SimpleNamespace(revision=0))
    assert captured[0].selector.field_filter.match_mode == "raw_regex"


def test_apply_requires_owned_preview_artifact(monkeypatch):
    store = SimpleNamespace(revision=0)
    request = QuickFieldChangeRequest(
        kind="delete-field",
        selector=FieldSelector(FieldFilter("")),
    )
    preview = QuickFieldChangePreview(
        request=request,
        request_json=renderer._canonical_request_json(request),
        store_id=id(store),
        store_revision=store.revision,
        output_path=Path("/tmp/missing-preview.mrc"),
    )
    monkeypatch.setattr(renderer, "_preview_artifact_is_valid", lambda value: False)
    calls = []
    fake = FakeStreamlit(
        session_state={renderer.K_PREVIEW: preview},
        pressed={renderer.K_APPLY_BUTTON},
    )
    _render(monkeypatch, fake, store=store, on_apply=lambda *args: calls.append(args))
    assert not calls
    assert any("stale" in message.lower() for message in fake.infos)


def test_current_preview_applies_preview_and_current_request(monkeypatch):
    store = SimpleNamespace(revision=0)
    request = QuickFieldChangeRequest(
        kind="delete-field",
        selector=FieldSelector(FieldFilter("")),
    )
    preview = QuickFieldChangePreview(
        request=request,
        request_json=renderer._canonical_request_json(request),
        store_id=id(store),
        store_revision=store.revision,
        output_path=Path("/tmp/preview.mrc"),
    )
    monkeypatch.setattr(renderer, "_preview_artifact_is_valid", lambda value: True)
    calls = []
    fake = FakeStreamlit(
        selections={"Operation": "Delete field"},
        session_state={renderer.K_PREVIEW: preview},
        pressed={renderer.K_APPLY_BUTTON},
    )
    _render(monkeypatch, fake, store=store, on_apply=lambda *args: calls.append(args))
    assert calls == [(preview, request)]


def test_real_owned_preview_gate_and_evidence_metrics(monkeypatch):
    runner = renderer.quick_field_change_runner
    workdir = runner._new_workdir()
    output = workdir / "output.mrc"
    output.write_bytes(b"candidate")
    preview = QuickFieldChangePreview(
        request=QuickFieldChangeRequest(kind="delete-field"),
        request_json="",
        output_path=output,
        workdir=workdir,
        record_count=3,
        changed_count=2,
        unchanged_count=1,
        skipped_count=0,
        fields_affected=2,
        subfields_affected=0,
        reason_counts={"no-filtered-fields": 1},
        diff_summary=TaskDiffSummary(
            changed_count=2,
            per_record_diffs=[
                PerRecordDiff(
                    record_index=0,
                    identifier="r1",
                    rows=[("=245  old", "=245  new", "changed")],
                )
            ],
        ),
    )
    try:
        assert renderer._preview_artifact_is_valid(preview)
        fake = FakeStreamlit()
        monkeypatch.setattr(renderer, "st", fake)
        renderer._render_preview_evidence(preview)
        assert ("Changed", 2) in fake.metrics
        assert any("no-filtered-fields: 1" in caption for caption in fake.captions)
        assert any("Record r1 changes" == label for label, _expanded in fake.expanders)
    finally:
        runner.cleanup_artifact(preview)


def test_summary_includes_selection_and_operation_parameters():
    selector = FieldSelector(
        FieldFilter(
            "245",
            subfield_code="a",
            match_mode="contains",
            match_value="Title",
            ignore_case=True,
        ),
        Occurrence(mode="numbered", number=2),
    )
    request = QuickFieldChangeRequest(
        kind="copy-field",
        selector=selector,
        destination_tag="246",
        destination_policy="replace_all",
    )
    summary = renderer._summary(request)
    assert "245" in summary and "$a contains 'Title'" in summary
    assert "Numbered matching field #2" in summary
    assert "246" in summary and "replace all" in summary
