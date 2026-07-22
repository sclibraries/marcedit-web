"""Performance-sensitive helpers for the Streamlit View renderer."""

from __future__ import annotations

from types import SimpleNamespace

from pymarc import Field, Record, Subfield

from marcedit_web.lib import search
from marcedit_web.render import view


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Column(_Context):
    def button(self, *args, **kwargs):
        return False

    def number_input(self, *args, **kwargs):
        return 1

    def selectbox(self, label, options, **kwargs):
        return options[0]

    def text_input(self, *args, **kwargs):
        return ""


class _Store:
    revision = 0

    def __init__(self, record):
        self.record = record

    def count(self):
        return 1

    def get(self, index):
        assert index == 0
        return self.record


def _record_with_tags(*tags: str) -> Record:
    record = Record()
    for tag in tags:
        if tag < "010":
            record.add_field(Field(tag=tag, data=f"value-{tag}"))
        else:
            record.add_field(
                Field(
                    tag=tag,
                    indicators=[" ", " "],
                    subfields=[Subfield("a", f"value-{tag}")],
                )
            )
    return record


def _render_events(monkeypatch, record):
    warnings = []
    events = []
    monkeypatch.setattr(view.session, "require_upload", lambda _purpose: True)
    monkeypatch.setattr(view.session, "current_store", lambda: _Store(record))
    monkeypatch.setattr(view.st, "session_state", {})
    monkeypatch.setattr(view.st, "text_input", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        view.st,
        "columns",
        lambda spec: [_Column() for _ in spec],
    )
    monkeypatch.setattr(view.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(view.st, "number_input", lambda *args, **kwargs: 1)
    monkeypatch.setattr(view.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(view.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(view.st, "expander", lambda *args, **kwargs: _Context())
    monkeypatch.setattr(view.st, "checkbox", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        view.st,
        "warning",
        lambda message: (warnings.append(message), events.append("warning")),
    )
    monkeypatch.setattr(
        view.st,
        "code",
        lambda *args, **kwargs: events.append("render"),
    )
    monkeypatch.setattr(view.help_lookup, "help_for", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        view.tooltips,
        "render_help_entry",
        lambda _entry: "",
    )
    monkeypatch.setattr(
        view.single_record_edit,
        "render_inline_edit",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        view.fixed_field_helper,
        "render_fixed_field_helper",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        view.fixed_field_helper,
        "render_008_helper",
        lambda **kwargs: None,
    )

    view.render(rule_set=SimpleNamespace())

    return warnings, events


def test_unfiltered_navigation_uses_arithmetic_for_large_batches():
    """A 100K batch must not require a list containing 100K record numbers."""
    state = view._navigation_state(
        total=100_000,
        requested=99_999,
        match_indices=None,
    )

    assert state.current == 99_999
    assert state.position == 99_998
    assert state.size == 100_000
    assert state.minimum == 1
    assert state.maximum == 100_000
    assert state.match_indices is None
    assert state.step(1) == 100_000


def test_filtered_navigation_uses_match_indices_without_copying_them():
    """Search navigation keeps the compact 0-based result list as-is."""
    matches = [4, 20, 99_999]

    state = view._navigation_state(
        total=100_000,
        requested=21,
        match_indices=matches,
    )

    assert state.current == 21
    assert state.position == 1
    assert state.size == 3
    assert state.match_indices is matches
    assert state.step(-1) == 5
    assert state.step(1) == 100_000


def test_navigation_clamps_unknown_search_record_to_first_match():
    state = view._navigation_state(
        total=100,
        requested=50,
        match_indices=[4, 20, 80],
    )

    assert state.current == 5
    assert state.position == 0


def test_search_results_are_reused_until_store_revision_changes():
    """Prev/Next reruns must not rescan an unchanged 100K batch."""
    store = SimpleNamespace(revision=0)
    query = search.parse_query("245$a:title")
    session_state = {}
    calls = []

    def _compute():
        calls.append(store.revision)
        return [2, 8]

    first = view._cached_match_indices(
        session_state, store, "245$a:title", _compute
    )
    second = view._cached_match_indices(
        session_state, store, "245$a:title", _compute
    )

    assert query.is_empty() is False
    assert first == second == [2, 8]
    assert calls == [0]

    store.revision = 1
    third = view._cached_match_indices(
        session_state, store, "245$a:title", _compute
    )

    assert third == [2, 8]
    assert calls == [0, 1]


def test_search_cache_is_released_when_search_is_cleared():
    state = {view._K_SEARCH_RESULTS: {"matches": list(range(100_000))}}

    view._clear_search_cache(state)

    assert view._K_SEARCH_RESULTS not in state


def test_view_renders_ascending_fields_without_order_warning(monkeypatch):
    warnings, events = _render_events(
        monkeypatch,
        _record_with_tags("001", "035", "040", "245"),
    )

    assert warnings == []
    assert events == ["render"]


def test_view_warns_before_rendering_fields_in_source_order(monkeypatch):
    warnings, events = _render_events(
        monkeypatch,
        _record_with_tags("001", "040", "035", "245"),
    )

    assert len(warnings) == 1
    assert "displayed in source order" in warnings[0]
    assert "040 before 035" in warnings[0]
    assert events == ["warning", "render"]


def test_view_order_warning_is_bounded_to_twenty_inversions(monkeypatch):
    warnings, _events = _render_events(
        monkeypatch,
        _record_with_tags(*(f"{number:03}" for number in range(22, 0, -1))),
    )

    assert len(warnings) == 1
    assert warnings[0].count(" before ") == 20
