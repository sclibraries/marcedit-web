"""View — render the loaded MARC records as `.mrk` text.

Read-only. Navigates record-by-record through `st.session_state.records`
with a 1-based index input and Prev / Next buttons. Optional tag filter
narrows the rendered `.mrk` to specific fields (e.g., 035, 856).

Click-through help on tags / byte positions is a separate stage (Stage 7);
this page just renders.
"""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session, viewer

st.set_page_config(page_title="View · marcedit-web", layout="wide")
session.init()

st.title("View")
st.caption("MarcEdit-style `.mrk` rendering of the loaded batch.")


# --- Sidebar status --------------------------------------------------------


with st.sidebar:
    st.header("marcedit-web")
    user = st.session_state.get("user", "anonymous")
    st.caption(f"Signed in as **{user}**")
    st.divider()
    if session.has_upload():
        st.caption(f"Loaded: `{session.current_filename() or '(unnamed)'}`")
        st.caption(f"{len(session.current_records())} records")
    else:
        st.caption("No file loaded yet.")


# --- Empty state -----------------------------------------------------------


if not session.has_upload():
    st.info(
        "Upload a `.mrc` file from the **Home** page first. View reads "
        "records already in this session."
    )
    st.stop()


records = session.current_records()
total = len(records)
if total == 0:
    st.warning("The loaded file produced no parseable records.")
    st.stop()


# --- Navigator -------------------------------------------------------------


# Streamlit reruns the script on every interaction; we hold the current
# index in session_state so Prev / Next survive across reruns.
if (
    "view_index" not in st.session_state
    or st.session_state["view_index"] > total
    or st.session_state["view_index"] < 1
):
    st.session_state["view_index"] = 1


def _step(delta: int) -> None:
    current = int(st.session_state.get("view_index", 1))
    nxt = current + delta
    if nxt < 1:
        nxt = 1
    elif nxt > total:
        nxt = total
    st.session_state["view_index"] = nxt


nav_a, nav_b, nav_c, nav_d = st.columns([1, 3, 1, 1])
with nav_a:
    st.button(
        "◀ Prev",
        on_click=_step,
        args=(-1,),
        disabled=st.session_state["view_index"] <= 1,
        use_container_width=True,
    )
with nav_b:
    st.number_input(
        "Record #",
        min_value=1,
        max_value=total,
        step=1,
        key="view_index",
        label_visibility="collapsed",
    )
with nav_c:
    st.button(
        "Next ▶",
        on_click=_step,
        args=(1,),
        disabled=st.session_state["view_index"] >= total,
        use_container_width=True,
    )
with nav_d:
    st.caption(f"of **{total}**")


# --- Banner ---------------------------------------------------------------


index = int(st.session_state["view_index"])
record = records[index - 1]
identifier = viewer.record_identifier(record)
title = viewer.record_title(record) or "(no 245 $a)"
st.markdown(
    f"**Record {index} of {total}** — `{identifier}` — {title}"
)


# --- Tag filter -----------------------------------------------------------


with st.expander("Filter fields", expanded=False):
    show_leader = st.checkbox(
        "Show leader (LDR)",
        value=True,
        help="When unchecked, the leader line is omitted from the output.",
    )
    tags_input = st.text_input(
        "Tags (blank = all)",
        placeholder="e.g. 035, 856 — comma or space separated",
        help=(
            "Filter to specific 3-character tags. Combine with the leader "
            "checkbox above. Blank field means: render every tag."
        ),
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
    # User hid the leader but didn't filter tags — render every tag except LDR.
    # `render_record` treats fields=None as "everything"; to drop just LDR we
    # need an explicit set of every tag present minus LDR.
    tag_filter = {f.tag for f in record.fields}


# --- Rendering ------------------------------------------------------------


text = viewer.render_record(record, fields=tag_filter)

# Streamlit's st.code preserves whitespace and uses a monospace font, which
# is exactly what `.mrk` needs to keep subfield delimiters and indicator
# columns aligned. `language="text"` disables syntax highlighting so the
# colors don't fight with the cataloger's eye.
st.code(text, language="text")
