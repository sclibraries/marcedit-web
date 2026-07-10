"""Performance-sensitive helpers for the Streamlit View renderer."""

from __future__ import annotations

from types import SimpleNamespace

from marcedit_web.lib import search
from marcedit_web.render import view


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
