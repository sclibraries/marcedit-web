"""Tests for the shared task operation reference."""

from marcedit_web.lib import task_builder
from marcedit_web.render import task_operation_reference


class FakeStreamlit:
    def __init__(self, query="", *, clicked=()):
        self.query = query
        self.clicked = set(clicked)
        self.text_inputs = []
        self.markdowns = []
        self.captions = []
        self.writes = []
        self.dialog_calls = []
        self.rerun_calls = 0

    def text_input(self, label, **kwargs):
        self.text_inputs.append({"label": label, **kwargs})
        return self.query

    def markdown(self, value):
        self.markdowns.append(value)

    def caption(self, value):
        self.captions.append(value)

    def write(self, value):
        self.writes.append(value)

    def dialog(self, title, *, width, dismissible):
        self.dialog_calls.append(
            {
                "title": title,
                "width": width,
                "dismissible": dismissible,
            }
        )

        def decorate(render):
            return render

        return decorate

    def button(self, label, **kwargs):
        return label in self.clicked

    def rerun(self):
        self.rerun_calls += 1


def test_reference_entries_are_alphabetical_and_search_label_or_summary():
    entries = task_operation_reference.reference_entries(
        include_custom=False,
    )
    labels = [entry["label"] for entry in entries]

    assert labels == sorted(labels, key=str.casefold)
    assert "Custom Python (advanced)" not in labels
    assert [
        entry["label"]
        for entry in task_operation_reference.reference_entries(
            include_custom=False,
            query="selected MARC value",
        )
    ] == ["Guided find and replace"]


def test_reference_entries_are_copies_not_palette_aliases():
    entries = task_operation_reference.reference_entries(include_custom=True)
    entries[0]["label"] = "changed"
    entries[0]["params"][0]["label"] = "nested change"

    assert all(
        entry["label"] != "changed"
        for entry in task_builder.OPERATIONS_PALETTE
    )
    assert all(
        parameter["label"] != "nested change"
        for entry in task_builder.OPERATIONS_PALETTE
        for parameter in entry["params"]
    )


def test_reference_entry_renders_palette_facts_and_syntax_link(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(task_operation_reference, "st", fake)
    entry = next(
        entry
        for entry in task_builder.OPERATIONS_PALETTE
        if entry["kind"] == "guided-find-replace"
    )

    task_operation_reference.render_reference_entry(entry)

    assert fake.markdowns == ["**Guided find and replace**"]
    assert fake.writes == ["Find and replace text in a selected MARC value."]
    assert any("guided-find-replace" in value for value in fake.captions)
    assert any(
        "docs/task-authoring-syntax.md" in value
        for value in fake.captions
    )


def test_reference_dialog_renders_searchable_alphabetical_browser(
    monkeypatch,
):
    fake = FakeStreamlit(query="field")
    rendered_labels = []
    monkeypatch.setattr(task_operation_reference, "st", fake)
    monkeypatch.setattr(
        task_operation_reference,
        "render_reference_entry",
        lambda entry: rendered_labels.append(entry["label"]),
    )

    task_operation_reference.open_reference_dialog(
        include_custom=False,
        on_close=lambda: None,
    )

    assert fake.dialog_calls == [{
        "title": "Operation reference",
        "width": "large",
        "dismissible": False,
    }]
    assert fake.text_inputs == [{
        "label": "Search operations",
        "key": "tasks_operation_reference_search",
    }]
    assert rendered_labels == sorted(rendered_labels, key=str.casefold)
    assert rendered_labels
    assert all(
        "field" in "{0} {1}".format(entry["label"], entry["summary"]).casefold()
        for entry in task_builder.OPERATIONS_PALETTE
        if entry["label"] in rendered_labels
    )


def test_reference_dialog_close_clears_parent_state_and_reruns(monkeypatch):
    fake = FakeStreamlit(clicked={"Close"})
    closed = []
    monkeypatch.setattr(task_operation_reference, "st", fake)

    task_operation_reference.open_reference_dialog(
        include_custom=False,
        on_close=lambda: closed.append(True),
    )

    assert closed == [True]
    assert fake.rerun_calls == 1
