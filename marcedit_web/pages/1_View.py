"""View — render the loaded MARC records as `.mrk` text.

Read-only. Navigates record-by-record through `st.session_state.records`
with a 1-based index input and Prev / Next buttons. Optional tag filter
narrows the rendered `.mrk` to specific fields (e.g., 035, 856). A "Field
help" expander resolves any (tag, subfield, byte) lookup against the
extended `data/marc-rules.txt`.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from marcedit_web.lib import help_lookup, rules, session, tooltips, viewer

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


# --- Rules parsing (cached) ----------------------------------------------


_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "marc-rules.txt"


@st.cache_data(show_spinner=False)
def _load_rules(path_str: str, mtime: float):
    return rules.parse_rules(Path(path_str))


def _rules_for_page() -> rules.RuleSet:
    if not _RULES_PATH.exists():
        return rules.RuleSet()
    rule_set, _ = _load_rules(str(_RULES_PATH), _RULES_PATH.stat().st_mtime)
    return rule_set


rule_set = _rules_for_page()


# --- Field help expander --------------------------------------------------


with st.expander("Field help", expanded=False):
    st.caption(
        "Look up a tag, subfield, or byte position against `data/marc-rules.txt`. "
        "Coverage depends on what `:help` / `:byte` directives have been added to "
        "the rules file — start with `008 byte 28` for the canonical example."
    )

    # Build the tag selector. Always include LDR + every tag present on
    # the current record, in record order with duplicates collapsed.
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
            "Zero-based byte position. Only meaningful for LDR, 006, 007, 008 "
            "(and other control fields)."
        ),
    )

    if hc_clear.button("Clear"):
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
    st.markdown(tooltips.render_help_entry(entry), unsafe_allow_html=True)


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
    tag_filter = {f.tag for f in record.fields}


# --- Rendering ------------------------------------------------------------


text = viewer.render_record(record, fields=tag_filter)
st.code(text, language="text")
