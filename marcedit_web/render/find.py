"""Find page renderer (TASK-042).

Match-set view of the loaded batch. Cataloger types a query
(literal, starts-with via ``^``, ends-with via ``$``, regex via
``~``, or AND-compound), the page returns a paginated table of
matches with per-row identifiers + title snippet + the matching
value, plus action buttons:

* Open the first match in View.
* Export the matched subset as a binary ``.mrc``.
* Send to the Quick find/replace wizard (just navigates for v1;
  passing a match-scope is a TASK-036 follow-up).
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
import pymarc
import streamlit as st

from marcedit_web.lib import search, session


# Per-page session-state keys. Stable strings, not constants, because
# this is the only file that uses them.
_K_QUERY = "find_query"
_K_RESULTS = "find_results"        # dict {indices, snippets, query_text}
_K_PAGE = "find_page"


_PAGE_SIZE = 25


def render() -> None:
    """Render the Find page."""
    if not session.require_upload("search the loaded batch"):
        return

    store = session.current_store()
    if store is None or store.count() == 0:
        st.warning("The loaded file produced no parseable records.")
        return

    st.caption(
        "Find records in the loaded batch. Use the operators below to "
        "go beyond plain substring search."
    )

    with st.expander("Query syntax", expanded=False):
        st.markdown(
            "* `foo` — records where any field contains `foo`.\n"
            "* `245:foo` — restrict to fields with this tag.\n"
            "* `245$a:foo` — restrict to a subfield.\n"
            "* `008/28:i` — match a single byte at a control-field "
            "position.\n"
            "* `245$a:^The` — value **starts with** the text.\n"
            "* `856$u:.pdf$` — value **ends with** the text "
            "(trailing `$` is the sigil).\n"
            "* `035$a:~^\\(EDZ\\)` — **regex** match. For catalogers "
            "comfortable with regex; bad patterns fall back to plain "
            "substring search and surface an error.\n"
            "* `clause1 AND clause2` — every clause must match.\n"
            "* `\"^literal\"` — quoted values disable operator "
            "interpretation."
        )

    query_text = st.text_input(
        "Search",
        value=st.session_state.get(_K_QUERY, ""),
        placeholder="e.g. 035$a:^EDZ  or  245$a:Pistoletto AND 008/35:e",
        key=_K_QUERY,
    )

    submit = st.button("Search", type="primary", key="find_submit_btn")

    if submit:
        _run_search(store, query_text)

    # TASK-046: drop cached results when the active batch changes.
    # Without this, switching to a different uploaded file could
    # render results that point at records in the previous batch.
    current_id = _batch_identity(store)
    results = st.session_state.get(_K_RESULTS)
    if results is not None and results.get("batch_identity") != current_id:
        st.session_state.pop(_K_RESULTS, None)
        results = None

    if results is not None and results["query_text"] == query_text:
        _render_results(store, results)


def _batch_identity(store) -> tuple[str, int]:
    """Stable ``(filename, count)`` snapshot of the active batch.

    Used to invalidate cached results when the cataloger swaps the
    loaded file between searches.
    """
    return (
        getattr(store, "filename", None) or "(unnamed)",
        store.count(),
    )


def _run_search(store, query_text: str) -> None:
    """Parse + execute the query; stash results in session_state."""
    queries = search.parse_compound_query(query_text)
    if not queries:
        st.warning("Enter a query above to search.")
        return

    errors = [q.parse_error for q in queries if q.parse_error]
    if errors:
        for err in errors:
            st.error(err)
        # We don't return here — the parser falls back to contains on
        # bad regex, so the search can still proceed. Cataloger sees
        # the warning AND the (now-degraded) results.

    # Index walk + snippet collection both scale with batch size.
    # Wrap both in one spinner so the user sees activity through the
    # whole search and not just the index pass.
    with st.spinner("Searching…"):
        indices = list(search.matching_records_compound(store, queries))

        # Pull display snippets for the table. We pull only what shows
        # in the table — 001, 245$a, and a match-snippet pulled from the
        # first matching haystack across the clauses. Cap snippet pulls
        # at the visible page later.
        rows = []
        for idx in indices:
            record = store.get(idx)
            if record is None:
                continue
            identifier = ""
            f001 = record.get("001")
            if f001 is not None:
                identifier = (f001.data or "")[:48]
            title = ""
            f245 = record.get("245")
            if f245 is not None and not f245.is_control_field():
                title = (f245.get("a") or "")[:80]
            match_snippet = _snippet_for(record, queries)
            rows.append({
                "#": idx + 1,
                "001": identifier,
                "245$a": title,
                "match": match_snippet,
            })

    st.session_state[_K_RESULTS] = {
        "query_text": query_text,
        "indices": indices,
        "rows": rows,
        "batch_identity": _batch_identity(store),
    }
    st.session_state[_K_PAGE] = 0


def _snippet_for(record, queries: list[search.SearchQuery]) -> str:
    """Return a short snippet showing one matched value across the clauses."""
    for query in queries:
        if query.is_empty():
            continue
        candidate = _first_matching_value(record, query)
        if candidate:
            return _truncate(candidate, 80)
    return ""


def _first_matching_value(record, query: search.SearchQuery) -> str:
    """Walk haystacks per the query and return the first hit's raw value."""
    if query.tag is None:
        # Any-field — return the first non-empty field value as a hint.
        for f in record.fields:
            if getattr(f, "data", None):
                return f.data
            for sf in f.subfields:
                if sf.value:
                    return f"{f.tag}${sf.code}: {sf.value}"
        return ""
    if query.byte_position is not None:
        f = record.get(query.tag)
        if f is None:
            return ""
        data = getattr(f, "data", None) or ""
        snippet_pos = max(0, query.byte_position - 4)
        return f"{query.tag} @{query.byte_position}: ...{data[snippet_pos:snippet_pos + 12]}..."
    if query.tag == "LDR":
        return f"LDR: {str(record.leader) if record.leader else ''}"
    for f in record.get_fields(query.tag):
        if f.is_control_field():
            return f"{query.tag}: {f.data or ''}"
        for sf in f.subfields:
            if query.subfield and sf.code != query.subfield:
                continue
            return f"{query.tag}${sf.code}: {sf.value}"
    return ""


def _truncate(s: str, length: int) -> str:
    return s if len(s) <= length else s[: length - 1] + "…"


def _render_results(store, results: dict) -> None:
    indices: list[int] = results["indices"]
    rows: list[dict] = results["rows"]
    total = store.count()

    st.divider()
    st.markdown(
        f"**{len(indices):,}** match(es) of **{total:,}** total records"
    )

    if not indices:
        return

    page = int(st.session_state.get(_K_PAGE, 0))
    pages = max(1, (len(rows) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, pages - 1))

    nav_a, nav_b, nav_c = st.columns([1, 2, 1])
    if nav_a.button(
        "◀ Prev", key="find_page_prev", disabled=page == 0,
    ):
        st.session_state[_K_PAGE] = page - 1
        st.rerun()
    nav_b.caption(
        f"Page {page + 1} of {pages} — showing rows "
        f"{page * _PAGE_SIZE + 1}–{min(len(rows), (page + 1) * _PAGE_SIZE)}"
    )
    if nav_c.button(
        "Next ▶", key="find_page_next", disabled=page >= pages - 1,
    ):
        st.session_state[_K_PAGE] = page + 1
        st.rerun()

    start = page * _PAGE_SIZE
    end = min(len(rows), start + _PAGE_SIZE)
    page_df = pd.DataFrame(rows[start:end])
    event = st.dataframe(
        page_df,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="find_table",
        column_config={
            "#": st.column_config.NumberColumn("Rec #", width="small"),
            "001": st.column_config.TextColumn("001", width="medium"),
            "245$a": st.column_config.TextColumn("Title (245$a)", width="large"),
            "match": st.column_config.TextColumn("Match", width="large"),
        },
    )
    from marcedit_web.render._record_modal import selection_view_button
    selection_view_button(
        df=page_df,
        event=event,
        record_column="#",
        button_label_template="View record #{n}",
        button_key="find_view_btn",
        store=store,
    )

    st.divider()
    _render_actions(store, indices)


def _render_actions(store, indices: list[int]) -> None:
    """Action buttons under the match table."""
    st.markdown("**Actions on this match set**")

    col_open, col_export, col_replace = st.columns(3)

    if col_open.button(
        "Open first match in View",
        key="find_action_open",
        help=(
            "Jumps to the View page and pre-sets the navigator to "
            "the first matching record."
        ),
    ):
        # The View page reads ``st.session_state["view_index"]`` as
        # the 1-based record number.
        st.session_state["view_index"] = indices[0] + 1
        st.success(
            f"Set View record # to {indices[0] + 1}. Open the View "
            "page from the sidebar."
        )

    if col_export.button(
        "Export matches as .mrc",
        key="find_action_export",
        help=(
            "Builds a .mrc containing only the matched records and "
            "offers a download."
        ),
    ):
        _offer_subset_download(store, indices)

    if col_replace.button(
        "Send to Quick find/replace",
        key="find_action_replace",
        help=(
            "Opens the Quick find/replace wizard on the Tasks page. "
            "For v1 the wizard still runs on the full batch — "
            "honoring a passed-in match scope is a follow-up."
        ),
    ):
        st.info(
            "Open the **Tasks** page from the sidebar and use the "
            "**Quick find/replace** expander. (Match-scope passthrough "
            "lands in a follow-up ticket.)"
        )


def _offer_subset_download(store, indices: list[int]) -> None:
    """Materialize the matched-records subset and offer a download."""
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-find-export-"))
    subset_path = workdir / "matches.mrc"
    with subset_path.open("wb") as fh:
        writer = pymarc.MARCWriter(fh)
        for idx in indices:
            rec = store.get(idx)
            if rec is not None:
                writer.write(rec)
    fname = session.stamped_filename("matches")
    st.download_button(
        f"⬇ Download {fname}",
        data=subset_path.read_bytes(),
        file_name=fname,
        mime="application/marc",
        key="find_dl_subset",
    )
