"""View tab — render a single record as `.mrk` with help lookup + search.

Also the 100K-safe inline-edit surface: any record can be opened in an
Ace `.mrk` editor for single-record mutation. The inline editor itself
lives in :mod:`marcedit_web.render.single_record_edit` (shared with
the Workspace Edit tab's over-cap branch).
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Any, Callable, MutableMapping, Sequence

import streamlit as st

from marcedit_web.lib import (
    help_lookup,
    rules as rules_mod,
    search,
    session,
    tooltips,
    viewer,
)
from marcedit_web.render import fixed_field_helper, single_record_edit


_K_SEARCH_RESULTS = "view_search_results"


@dataclass(frozen=True)
class _NavigationState:
    total: int
    current: int
    position: int
    size: int
    minimum: int
    maximum: int
    match_indices: Sequence[int] | None

    def step(self, delta: int) -> int:
        if self.match_indices is None:
            return min(self.total, max(1, self.current + delta))
        if not self.match_indices:
            return self.current
        position = min(
            len(self.match_indices) - 1,
            max(0, self.position + delta),
        )
        return self.match_indices[position] + 1


def _navigation_state(
    *,
    total: int,
    requested: int,
    match_indices: Sequence[int] | None,
) -> _NavigationState:
    """Resolve one-based navigation without expanding the full batch range."""
    current = min(total, max(1, requested))
    if match_indices is None:
        return _NavigationState(
            total=total,
            current=current,
            position=current - 1,
            size=total,
            minimum=1,
            maximum=total,
            match_indices=None,
        )
    if not match_indices:
        return _NavigationState(
            total=total,
            current=current,
            position=0,
            size=1,
            minimum=current,
            maximum=current,
            match_indices=match_indices,
        )

    position = bisect_left(match_indices, current - 1)
    if position >= len(match_indices) or match_indices[position] != current - 1:
        position = 0
        current = match_indices[0] + 1
    return _NavigationState(
        total=total,
        current=current,
        position=position,
        size=len(match_indices),
        minimum=match_indices[0] + 1,
        maximum=match_indices[-1] + 1,
        match_indices=match_indices,
    )


def _cached_match_indices(
    state: MutableMapping[str, Any],
    store,
    query_text: str,
    compute: Callable[[], Sequence[int]],
) -> list[int]:
    """Return query results cached for this store object and revision."""
    token = (id(store), store.revision, query_text)
    cached = state.get(_K_SEARCH_RESULTS)
    if cached is not None and cached.get("token") == token:
        return cached["matches"]
    matches = list(compute())
    state[_K_SEARCH_RESULTS] = {"token": token, "matches": matches}
    return matches


def _clear_search_cache(state: MutableMapping[str, Any]) -> None:
    state.pop(_K_SEARCH_RESULTS, None)


def render(rule_set: rules_mod.RuleSet | None = None) -> None:
    """Render the View tab into the current Streamlit container."""
    if not session.require_upload("view records here"):
        return

    store = session.current_store()
    total = store.count() if store else 0
    if total == 0:
        st.warning("The loaded file produced no parseable records.")
        return

    if rule_set is None:
        from marcedit_web.render import rules_for_page
        rule_set = rules_for_page()

    # --- Search bar (above the navigator) ----------------------------------

    query_str = st.text_input(
        "Search",
        placeholder=(
            "Try `245$a:Pistoletto`, `008/28: ` (with quotes), `LDR/6:a`, "
            "or just plain text."
        ),
        key="view_search_query",
        help=(
            "Query syntax: `text` (any field), `tag:text`, `tag$sub:text`, "
            "`tag/byte:text`, `tag$sub:\"exact phrase\"`. Matching is "
            "case-insensitive."
        ),
    )

    query = search.parse_query(query_str or "")
    search_active = not query.is_empty()
    match_indices: list[int] = []
    if search_active:
        def _run_search() -> list[int]:
            # A new query walks every record. Cached results make subsequent
            # Prev/Next reruns independent of batch size.
            with st.spinner("Searching…"):
                return list(search.matching_records(store, query))

        match_indices = _cached_match_indices(
            st.session_state,
            store,
            query_str,
            _run_search,
        )
        if not match_indices:
            st.warning(f"No records match `{query_str}`.")
        else:
            st.caption(
                f"`{len(match_indices)}` match(es) for `{query_str}`. "
                f"Prev / Next jump between matches."
            )
    else:
        _clear_search_cache(st.session_state)

    navigation = _navigation_state(
        total=total,
        requested=int(st.session_state.get("view_index", 1)),
        match_indices=match_indices if search_active else None,
    )
    st.session_state["view_index"] = navigation.current

    def _step(delta: int) -> None:
        current_state = _navigation_state(
            total=total,
            requested=int(st.session_state.get("view_index", 1)),
            match_indices=match_indices if search_active else None,
        )
        st.session_state["view_index"] = current_state.step(delta)

    nav_a, nav_b, nav_c, nav_d = st.columns([1, 3, 1, 1])
    with nav_a:
        st.button(
            "◀ Prev",
            on_click=_step,
            args=(-1,),
            disabled=navigation.position <= 0,
            use_container_width=True,
            key="view_prev",
        )
    with nav_b:
        st.number_input(
            "Record #",
            min_value=navigation.minimum,
            max_value=navigation.maximum,
            step=1,
            key="view_index",
            label_visibility="collapsed",
        )
    with nav_c:
        st.button(
            "Next ▶",
            on_click=_step,
            args=(1,),
            disabled=navigation.position >= navigation.size - 1,
            use_container_width=True,
            key="view_next",
        )
    with nav_d:
        if search_active and match_indices:
            st.caption(
                f"match {navigation.position + 1} of **{navigation.size}**"
            )
        else:
            st.caption(f"of **{total}**")

    index = int(st.session_state["view_index"])
    record = store.get(index - 1)
    if record is None:
        st.warning(f"Record {index} not found.")
        return
    identifier = viewer.record_identifier(record)
    title = viewer.record_title(record) or "(no 245 $a)"
    if search_active and match_indices:
        st.markdown(
            f"**Match {navigation.position + 1} of {navigation.size}** "
            f"(record #{index} of {total}) — `{identifier}` — {title}"
        )
    else:
        st.markdown(
            f"**Record {index} of {total}** — `{identifier}` — {title}"
        )

    # --- Field help expander -----------------------------------------------

    with st.expander("Field help", expanded=False):
        st.caption(
            "Look up a tag, subfield, or byte position against "
            "`data/marc-rules.txt`. Coverage depends on what `:help` / "
            "`:byte` directives have been added to the rules file — start "
            "with `008 byte 28` for the canonical example."
        )

        tags_in_record: list[str] = []
        seen: set[str] = set()
        for f in record.fields:
            if f.tag not in seen:
                tags_in_record.append(f.tag)
                seen.add(f.tag)
        tag_options = ["LDR"] + tags_in_record

        hc_tag, hc_sub, hc_byte, hc_clear = st.columns([2, 1, 1, 1])
        help_tag = hc_tag.selectbox(
            "Tag",
            options=tag_options,
            key="help_tag",
        )

        is_control = help_tag == "LDR" or (
            len(help_tag) == 3
            and help_tag.isdigit()
            and help_tag.startswith("00")
            and help_tag != "000"
        )

        help_subfield = hc_sub.text_input(
            "Subfield code",
            max_chars=1,
            placeholder="a",
            key="help_subfield",
            disabled=is_control,
            help=(
                "Single character. Disabled for control fields and the leader; "
                "use the byte input on the right instead."
            ),
        )

        help_byte_raw = hc_byte.text_input(
            "Byte position",
            placeholder="28",
            key="help_byte",
            disabled=not is_control,
            help=(
                "Zero-based byte position. Only meaningful for LDR, 006, 007, "
                "008 (and other control fields)."
            ),
        )

        if hc_clear.button("Clear", key="help_clear_btn"):
            st.session_state.pop("help_subfield", None)
            st.session_state.pop("help_byte", None)
            st.rerun()

        byte_position: int | None = None
        if is_control and help_byte_raw.strip():
            try:
                byte_position = int(help_byte_raw.strip())
            except ValueError:
                st.warning(f"`{help_byte_raw!r}` is not a number; ignoring.")

        entry = help_lookup.help_for(
            rule_set,
            tag=help_tag,
            subfield=(help_subfield or None) if not is_control else None,
            byte=byte_position,
        )
        # Trust source: data/marc-rules.txt (operator-controlled). Plain-text
        # fields are HTML-escaped inside render_help_entry; body is allowed
        # to contain markdown + safe HTML by design. See tooltips.py.
        st.markdown(tooltips.render_help_entry(entry), unsafe_allow_html=True)

    # --- Tag filter -------------------------------------------------------

    with st.expander("Filter fields", expanded=False):
        show_leader = st.checkbox(
            "Show leader (LDR)",
            value=True,
            help="When unchecked, the leader line is omitted from the output.",
            key="view_show_leader",
        )
        tags_input = st.text_input(
            "Tags (blank = all)",
            placeholder="e.g. 035, 856 — comma or space separated",
            help=(
                "Filter to specific 3-character tags. Combine with the leader "
                "checkbox above. Blank field means: render every tag."
            ),
            key="view_tags_input",
        )

    tag_filter: set[str] | None = None
    if tags_input.strip():
        try:
            tag_filter = viewer.parse_fields(tags_input)
        except ValueError as exc:
            st.warning(f"Could not parse tag filter: {exc}")
            tag_filter = None
        else:
            if show_leader:
                tag_filter.add("LDR")
    elif not show_leader:
        tag_filter = {f.tag for f in record.fields}

    inversions = viewer.field_order_inversions(record)
    if inversions:
        transitions = ", ".join(
            f"{previous} before {current}" for previous, current in inversions
        )
        st.warning(
            "Fields are displayed in source order, but tag order decreases at: "
            + transitions
        )

    text = viewer.render_record_human(record, fields=tag_filter)
    st.code(text, language="text")

    single_record_edit.render_inline_edit(
        store=store,
        index=index,
        record=record,
        rule_set=rule_set,
        key_prefix="view_edit",
    )

    fixed_field_helper.render_fixed_field_helper(
        store=store,
        index=index,
        record=record,
        key_prefix="view_control",
    )

    fixed_field_helper.render_008_helper(
        store=store,
        index=index,
        record=record,
        key_prefix="view_008",
    )
